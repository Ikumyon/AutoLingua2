import type { TextKey } from './i18n';
import { firstTranslationLabels } from './firstTranslationImageLabels';

export type ImageLabel = {
  text: TextKey;
  x: number;
  y: number;
  width: number;
  height: number;
  button?: boolean;
  fontSize?: number;
  background?: string;
};

const shared: ImageLabel[] = [
  { text: 'setup.imageText.title', x: 43, y: 9, width: 580, height: 28 },
  { text: 'setup.imageText.steps', x: 17, y: 61, width: 650, height: 26 },
  { text: 'setup.navigation.back.label', x: 23, y: 747, width: 112, height: 25, button: true },
  { text: 'setup.navigation.skip.label', x: 154, y: 747, width: 120, height: 25, button: true, fontSize: 16 },
];

// Coordinates refer to the original 934 × 796 screenshots; SVG scales them together.
export const imageLabels: Record<string, ImageLabel[]> = {
  ...firstTranslationLabels,
  '/images/setup/ai-selection.webp': [
    ...shared,
    { text: 'setup.imageText.choose', x: 32, y: 108, width: 650, height: 27 },
    { text: 'setup.imageText.later', x: 32, y: 143, width: 650, height: 27 },
    { text: 'setup.aiSelection.chatgpt.label', x: 89, y: 198, width: 650, height: 28 },
    { text: 'setup.aiSelection.chatgpt.body', x: 49, y: 236, width: 820, height: 28, fontSize: 17 },
    { text: 'setup.imageText.claude', x: 49, y: 315, width: 820, height: 28, fontSize: 17 },
    { text: 'setup.imageText.gemini', x: 49, y: 393, width: 820, height: 28, fontSize: 17 },
    { text: 'setup.aiSelection.openai.body', x: 49, y: 472, width: 820, height: 28, fontSize: 17 },
    { text: 'setup.navigation.next.label', x: 800, y: 747, width: 109, height: 25, button: true },
  ],
  '/images/setup/connection-success.webp': [
    ...shared,
    { text: 'setup.aiSelection.chatgpt.label', x: 32, y: 108, width: 650, height: 28 },
    { text: 'setup.imageText.signedIn', x: 63, y: 150, width: 296, height: 28 },
    { text: 'setup.imageText.logout', x: 375, y: 151, width: 110, height: 25, button: true },
    { text: 'setup.imageText.refresh', x: 508, y: 151, width: 111, height: 25, button: true, fontSize: 14 },
    { text: 'setup.imageText.models', x: 32, y: 192, width: 200, height: 28 },
    { text: 'setup.imageText.add', x: 42, y: 568, width: 414, height: 25, button: true },
    { text: 'setup.imageText.reset', x: 478, y: 568, width: 414, height: 25, button: true },
    { text: 'setup.aiConnection.test.label', x: 42, y: 616, width: 850, height: 25, button: true },
    { text: 'setup.imageText.result', x: 32, y: 654, width: 600, height: 29 },
    { text: 'setup.navigation.finish.label', x: 800, y: 747, width: 109, height: 25, button: true },
  ],
};
