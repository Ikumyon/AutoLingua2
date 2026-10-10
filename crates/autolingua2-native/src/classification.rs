//! Unicode edit distances, metric indexing and linear-space edit alignment.
use std::collections::BTreeMap;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc};
use std::time::Duration;

use pyo3::prelude::*;
use rayon::prelude::*;

type EditSpan = (String, usize, usize, usize, usize);
type CancelCheck<'a> = dyn Fn() -> PyResult<()> + Sync + 'a;

// Avoid dispatching tiny comparisons to the pool.
const PARALLEL_WORK: usize = 32_768;

fn check_cancelled(cancel: &Py<PyAny>) -> PyResult<()> {
    Python::attach(|py| cancel.call0(py).map(|_| ()))
}

fn shared_cancel(flag: &AtomicBool) -> PyResult<()> {
    if flag.load(Ordering::Relaxed) {
        Err(pyo3::exceptions::PyRuntimeError::new_err("Classification cancelled"))
    } else {
        Ok(())
    }
}

fn run_parallel<R, F>(cancel: Py<PyAny>, operation: F) -> PyResult<R>
where
    R: Send + 'static,
    F: FnOnce(Arc<AtomicBool>) -> PyResult<R> + Send + 'static,
{
    check_cancelled(&cancel)?;
    let cancelled = Arc::new(AtomicBool::new(false));
    let worker_cancelled = Arc::clone(&cancelled);
    let (sender, receiver) = mpsc::sync_channel(1);
    rayon::spawn(move || {
        let result = catch_unwind(AssertUnwindSafe(|| operation(worker_cancelled)))
            .unwrap_or_else(|_| Err(pyo3::exceptions::PyRuntimeError::new_err("Classification worker panicked")));
        let _ = sender.send(result);
    });
    let mut cancellation_error = None;
    loop {
        // Python ContextVars belong to the calling thread. Never call this on pool workers.
        if cancellation_error.is_none() {
            if let Err(error) = check_cancelled(&cancel) {
                cancelled.store(true, Ordering::Relaxed);
                cancellation_error = Some(error);
            }
        }
        match receiver.recv_timeout(Duration::from_millis(25)) {
            Ok(result) => {
                if let Some(error) = cancellation_error {
                    return Err(error);
                }
                check_cancelled(&cancel)?;
                return result;
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                return Err(cancellation_error.unwrap_or_else(|| {
                    pyo3::exceptions::PyRuntimeError::new_err("Classification worker disconnected")
                }));
            }
        }
    }
}

fn trim_equal<'a>(a: &'a [char], b: &'a [char]) -> (&'a [char], &'a [char], usize) {
    let prefix = a.iter().zip(b).take_while(|(x, y)| x == y).count();
    let a = &a[prefix..];
    let b = &b[prefix..];
    let suffix = a.iter().rev().zip(b.iter().rev()).take_while(|(x, y)| x == y).count();
    (&a[..a.len() - suffix], &b[..b.len() - suffix], prefix)
}

fn edit_distance(
    a: &[char], b: &[char], limit: Option<usize>, cancel: &CancelCheck<'_>,
) -> PyResult<Option<usize>> {
    cancel()?;
    let (a, b, _) = trim_equal(a, b);
    let (a, b) = if a.len() >= b.len() { (a, b) } else { (b, a) };
    let bound = limit.unwrap_or(a.len()).min(a.len());
    if a.len() - b.len() > bound {
        return Ok(None);
    }
    if b.is_empty() {
        return Ok(Some(a.len()));
    }
    let infinity = bound.saturating_add(1);
    let mut previous = vec![infinity; b.len() + 1];
    for (j, value) in previous.iter_mut().enumerate().take(bound.saturating_add(1)) {
        *value = j;
    }
    let mut current = vec![infinity; b.len() + 1];
    for i in 1..=a.len() {
        if i % 256 == 0 {
            cancel()?;
        }
        let start = i.saturating_sub(bound).max(1);
        let end = i.saturating_add(bound).min(b.len());
        current[0] = if i <= bound { i } else { infinity };
        if start > 1 {
            current[start - 1] = infinity;
        }
        let mut minimum = current[0];
        for j in start..=end {
            current[j] = (previous[j] + 1)
                .min(current[j - 1] + 1)
                .min(previous[j - 1] + usize::from(a[i - 1] != b[j - 1]))
                .min(infinity);
            minimum = minimum.min(current[j]);
        }
        if end < b.len() {
            current[end + 1] = infinity;
        }
        if minimum > bound {
            return Ok(None);
        }
        std::mem::swap(&mut previous, &mut current);
    }
    Ok((previous[b.len()] <= bound).then_some(previous[b.len()]))
}

fn exact_distance(a: &[char], b: &[char], cancel: &CancelCheck<'_>) -> PyResult<usize> {
    edit_distance(a, b, None, cancel)?.ok_or_else(|| {
        pyo3::exceptions::PyRuntimeError::new_err("Unbounded edit distance was rejected")
    })
}

#[pyfunction]
pub fn distances(
    py: Python<'_>, a: &str, jobs: Vec<(String, Option<usize>)>, cancel: Py<PyAny>,
) -> PyResult<Vec<Option<usize>>> {
    let a: Vec<char> = a.chars().collect();
    let jobs: Vec<(Vec<char>, Option<usize>)> = jobs.into_iter()
        .map(|(value, limit)| (value.chars().collect(), limit)).collect();
    let work = jobs.iter().fold(0usize, |total, (b, _)| total.saturating_add(a.len().saturating_mul(b.len())));
    py.detach(move || {
        if jobs.len() >= 2 && work >= PARALLEL_WORK {
            run_parallel(cancel, move |flag| {
                let check = || shared_cancel(&flag);
                jobs.into_par_iter().map(|(b, limit)| edit_distance(&a, &b, limit, &check)).collect()
            })
        } else {
            let check = || check_cancelled(&cancel);
            jobs.into_iter().map(|(b, limit)| edit_distance(&a, &b, limit, &check)).collect()
        }
    })
}

#[derive(Clone)]
struct Node {
    value: Vec<char>,
    key: usize,
    children: BTreeMap<usize, usize>,
}

/// A BK-tree over the actual edit-distance metric, not normalized similarity.
#[pyclass]
pub struct DistanceIndex {
    nodes: Arc<Vec<Node>>,
}

fn query_nodes(
    nodes: &[Node], value: &[char], radius: usize, cancel: &CancelCheck<'_>, parallel: bool,
) -> PyResult<Vec<(usize, usize)>> {
    cancel()?;
    let mut result = Vec::new();
    let mut frontier = if nodes.is_empty() { Vec::new() } else { vec![0] };
    while !frontier.is_empty() {
        let work = frontier.iter().fold(0usize, |total, &position| {
            total.saturating_add(value.len().saturating_mul(nodes[position].value.len()))
        });
        let evaluate = |&position: &usize| {
            exact_distance(value, &nodes[position].value, cancel).map(|d| (position, d))
        };
        let evaluated: Vec<(usize, usize)> = if parallel && frontier.len() >= 2 && work >= PARALLEL_WORK {
            frontier.par_iter().map(evaluate).collect::<PyResult<_>>()?
        } else {
            frontier.iter().map(evaluate).collect::<PyResult<_>>()?
        };
        frontier.clear();
        for (position, d) in evaluated {
            let node = &nodes[position];
            if d <= radius {
                result.push((node.key, d));
            }
            for (_, &child) in node.children.range(d.saturating_sub(radius)..=d.saturating_add(radius)) {
                frontier.push(child);
            }
        }
    }
    Ok(result)
}

#[pymethods]
impl DistanceIndex {
    #[new]
    fn new() -> Self {
        Self { nodes: Arc::new(Vec::new()) }
    }

    fn add(&mut self, py: Python<'_>, value: &str, key: usize, cancel: Py<PyAny>) -> PyResult<()> {
        let value: Vec<char> = value.chars().collect();
        let nodes = Arc::make_mut(&mut self.nodes);
        py.detach(|| {
            check_cancelled(&cancel)?;
            let check = || check_cancelled(&cancel);
            if nodes.is_empty() {
                nodes.push(Node { value, key, children: BTreeMap::new() });
                return Ok(());
            }
            let mut position = 0;
            loop {
                let d = exact_distance(&value, &nodes[position].value, &check)?;
                if let Some(&next) = nodes[position].children.get(&d) {
                    position = next;
                } else {
                    let next = nodes.len();
                    nodes[position].children.insert(d, next);
                    nodes.push(Node { value, key, children: BTreeMap::new() });
                    return Ok(());
                }
            }
        })
    }

    fn query(
        &self, py: Python<'_>, value: &str, radius: usize, cancel: Py<PyAny>,
    ) -> PyResult<Vec<(usize, usize)>> {
        let value: Vec<char> = value.chars().collect();
        let nodes = Arc::clone(&self.nodes);
        py.detach(move || {
            if nodes.len() >= 8 {
                run_parallel(cancel, move |flag| {
                    let check = || shared_cancel(&flag);
                    query_nodes(&nodes, &value, radius, &check, true)
                })
            } else {
                let check = || check_cancelled(&cancel);
                query_nodes(&nodes, &value, radius, &check, false)
            }
        })
    }
}

fn cost_row(a: &[char], b: &[char], cancel: &CancelCheck<'_>) -> PyResult<Vec<usize>> {
    let mut previous: Vec<usize> = (0..=b.len()).collect();
    let mut current = vec![0; b.len() + 1];
    for (i, ac) in a.iter().enumerate() {
        if i % 256 == 0 {
            cancel()?;
        }
        current[0] = i + 1;
        for (j, bc) in b.iter().enumerate() {
            current[j + 1] = (current[j] + 1)
                .min(previous[j + 1] + 1)
                .min(previous[j] + usize::from(ac != bc));
        }
        std::mem::swap(&mut previous, &mut current);
    }
    Ok(previous)
}

fn align_small(
    a: &[char], b: &[char], x: usize, y: usize, output: &mut Vec<EditSpan>, cancel: &CancelCheck<'_>,
) -> PyResult<()> {
    let width = b.len() + 1;
    let mut costs = vec![0; (a.len() + 1) * width];
    for i in 0..=a.len() {
        costs[i * width] = i;
    }
    for j in 0..width {
        costs[j] = j;
    }
    for i in 1..=a.len() {
        if i % 256 == 0 {
            cancel()?;
        }
        for j in 1..=b.len() {
            costs[i * width + j] = (costs[(i - 1) * width + j] + 1)
                .min(costs[i * width + j - 1] + 1)
                .min(costs[(i - 1) * width + j - 1] + usize::from(a[i - 1] != b[j - 1]));
        }
    }
    let (mut i, mut j) = (a.len(), b.len());
    let mut reversed = Vec::new();
    while i > 0 || j > 0 {
        if i > 0 && j > 0 && costs[i * width + j]
            == costs[(i - 1) * width + j - 1] + usize::from(a[i - 1] != b[j - 1])
        {
            if a[i - 1] != b[j - 1] {
                reversed.push(("replace".to_owned(), x + i - 1, x + i, y + j - 1, y + j));
            }
            i -= 1;
            j -= 1;
        } else if i > 0 && costs[i * width + j] == costs[(i - 1) * width + j] + 1 {
            reversed.push(("delete".to_owned(), x + i - 1, x + i, y + j, y + j));
            i -= 1;
        } else {
            reversed.push(("insert".to_owned(), x + i, x + i, y + j - 1, y + j));
            j -= 1;
        }
    }
    output.extend(reversed.into_iter().rev());
    Ok(())
}

fn align(
    a: &[char], b: &[char], x: usize, y: usize, output: &mut Vec<EditSpan>, cancel: &CancelCheck<'_>,
) -> PyResult<()> {
    cancel()?;
    let (a, b, prefix) = trim_equal(a, b);
    let (x, y) = (x + prefix, y + prefix);
    if a.is_empty() {
        if !b.is_empty() {
            output.push(("insert".to_owned(), x, x, y, y + b.len()));
        }
    } else if b.is_empty() {
        output.push(("delete".to_owned(), x, x + a.len(), y, y));
    } else if a.len() == 1 || b.len() == 1 {
        align_small(a, b, x, y, output, cancel)?;
    } else {
        let middle = a.len() / 2;
        let split = {
            let left = cost_row(&a[..middle], b, cancel)?;
            let reversed_a: Vec<char> = a[middle..].iter().rev().copied().collect();
            let reversed_b: Vec<char> = b.iter().rev().copied().collect();
            let right = cost_row(&reversed_a, &reversed_b, cancel)?;
            let mut best_split = 0;
            let mut best_cost = usize::MAX;
            for j in 0..=b.len() {
                let cost = left[j] + right[b.len() - j];
                if cost < best_cost {
                    best_split = j;
                    best_cost = cost;
                }
            }
            best_split
        };
        align(&a[..middle], &b[..split], x, y, output, cancel)?;
        align(&a[middle..], &b[split..], x + middle, y + split, output, cancel)?;
    }
    Ok(())
}

fn edit_spans(a: &[char], b: &[char], cancel: &CancelCheck<'_>) -> PyResult<Vec<EditSpan>> {
    let mut edits = Vec::new();
    align(a, b, 0, 0, &mut edits, cancel)?;
    let mut merged: Vec<EditSpan> = Vec::new();
    for edit in edits {
        if let Some(last) = merged.last_mut() {
            if last.0 == edit.0 && last.2 == edit.1 && last.4 == edit.3 {
                last.2 = edit.2;
                last.4 = edit.4;
                continue;
            }
        }
        merged.push(edit);
    }
    Ok(merged)
}

fn analyze(
    a: &[char], a_comparison: &[char], b: &[char], b_comparison: &[char], cancel: &CancelCheck<'_>,
) -> PyResult<(usize, Vec<EditSpan>)> {
    let edits = exact_distance(a_comparison, b_comparison, cancel)?;
    let spans = edit_spans(a, b, cancel)?;
    Ok((edits, spans))
}

#[pyfunction]
pub fn analyze_batch(
    py: Python<'_>, a: &str, a_comparison: &str, jobs: Vec<(String, String)>, cancel: Py<PyAny>,
) -> PyResult<Vec<(usize, Vec<EditSpan>)>> {
    let a: Vec<char> = a.chars().collect();
    let a_comparison: Vec<char> = a_comparison.chars().collect();
    let jobs: Vec<(Vec<char>, Vec<char>)> = jobs.into_iter()
        .map(|(b, comparison)| (b.chars().collect(), comparison.chars().collect())).collect();
    let work = jobs.iter().fold(0usize, |total, (b, comparison)| {
        total.saturating_add(a.len().saturating_mul(b.len()))
            .saturating_add(a_comparison.len().saturating_mul(comparison.len()))
    });
    py.detach(move || {
        if jobs.len() >= 2 && work >= PARALLEL_WORK {
            run_parallel(cancel, move |flag| {
                let check = || shared_cancel(&flag);
                jobs.into_par_iter().map(|(b, comparison)| analyze(&a, &a_comparison, &b, &comparison, &check)).collect()
            })
        } else {
            let check = || check_cancelled(&cancel);
            jobs.into_iter().map(|(b, comparison)| analyze(&a, &a_comparison, &b, &comparison, &check)).collect()
        }
    })
}

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<DistanceIndex>()?;
    module.add_function(wrap_pyfunction!(distances, module)?)?;
    module.add_function(wrap_pyfunction!(analyze_batch, module)?)?;
    Ok(())
}
