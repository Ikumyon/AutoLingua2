import { createContext, useContext } from 'react';
import { z } from 'zod';

const change = z.object({
  id: z.string(), label: z.string().optional(), key: z.string().optional(),
  before: z.unknown().optional(), after: z.unknown().optional(), language: z.string().optional(),
});
const operation = z.object({
  operation_id: z.string(), name: z.string(), status: z.string(),
  can_undo: z.boolean().optional(), changes: z.array(change),
});
const job = z.object({
  id: z.string(), kind: z.string(), status: z.string(), total: z.number().optional(),
  completed: z.number().optional(), error: z.string().optional(), results: z.array(z.unknown()).optional(),
});
export const snapshotSchema = z.object({
  items: z.array(z.discriminatedUnion('kind', [
    z.object({ id: z.string(), kind: z.literal('message'), role: z.string(), text: z.string(), model: z.string(),
      provider: z.string(), icon: z.string() }),
    z.object({ id: z.string(), kind: z.literal('operation'), document: operation }),
    z.object({ id: z.string(), kind: z.literal('job'), document: job }),
  ])),
  busy: z.boolean(), dark: z.boolean(), labels: z.record(z.string(), z.string()), colors: z.record(z.string(), z.string()),
  markdownIcon: z.string(),
});
export type Snapshot = z.infer<typeof snapshotSchema>;
export type Item = Snapshot['items'][number];
export type UiAction =
  | { type: 'copy'; text: string }
  | { type: 'open_link'; url: string }
  | { type: 'submit'; itemId: string; text: string }
  | { type: 'apply_operation'; id: string; ids: string[] }
  | { type: 'discard_operation' | 'undo_operation' | 'view_operation' | 'cancel_job'; id: string };

export interface NativeBridge {
  changed: { connect: (callback: (payload: string) => void) => void };
  ready: (instructions: string) => void;
  act: (payload: string) => void;
}
declare global {
  interface Window {
    QWebChannel: new (transport: unknown, callback: (channel: { objects: { chat: NativeBridge } }) => void) => unknown;
    qt: { webChannelTransport: unknown };
  }
}
export const ChatContext = createContext<{ snapshot: Snapshot; act: (action: UiAction) => void } | null>(null);
export function useChat() {
  const context = useContext(ChatContext);
  if (context === null) throw new Error('Chat bridge is not connected');
  return context;
}
export function useLabel() {
  const { snapshot } = useChat();
  return (key: string) => snapshot.labels[key] ?? key;
}
export function display(value: unknown): string {
  return value === undefined || value === null ? '' : typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}
