/** Embed data as inert JSON, escaping HTML closing tags and literal replacement metacharacters. */
export function packageHtml(
  template: string,
  style: string,
  script: string,
  data: string,
): string {
  JSON.parse(data);
  const escaped = data
    .replaceAll("<", "\\u003c")
    .replaceAll("\u2028", "\\u2028")
    .replaceAll("\u2029", "\\u2029");
  return template
    .replace("__STYLE__", () => style)
    .replace("__DATA__", () => escaped)
    .replace("__SCRIPT__", () => script.replace(/<\/script/gi, "<\\/script"));
}
