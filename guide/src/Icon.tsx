import {
  faArrowLeft, faArrowRight, faArrowUpRightFromSquare, faBars,
  faBookOpen, faChevronRight, faCircleInfo, faGlobe, faXmark, faSun, faMoon, faPlay, faCopy, faCheck,
} from '@fortawesome/free-solid-svg-icons';

const icons = {
  arrowLeft: faArrowLeft,
  arrowRight: faArrowRight,
  externalLink: faArrowUpRightFromSquare,
  menu: faBars,
  close: faXmark,
  book: faBookOpen,
  chevronRight: faChevronRight,
  info: faCircleInfo,
  language: faGlobe,
  sun: faSun,
  moon: faMoon,
  play: faPlay,
  copy: faCopy,
  check: faCheck,
};

// Decorative icons share sizing and never duplicate their control's accessible name.
export function Icon({ name, className = '' }: { name: keyof typeof icons; className?: string }) {
  const [width, height, , , paths] = icons[name].icon;
  return <svg className={`icon ${className}`} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false" fill="currentColor">
    {(Array.isArray(paths) ? paths : [paths]).map((path, index) => <path key={index} d={path} />)}
  </svg>;
}
