declare module '*.css';
declare module 'virtual:guide-languages' {
  const languages: { code: string; label: string }[];
  export default languages;
}
declare module 'virtual:guide-default-locale' {
  const dictionary: typeof import('../public/locales/ja.json');
  export default dictionary;
}
