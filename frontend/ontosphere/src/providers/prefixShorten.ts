export function prefixShorten(iri: string, prefixes: Record<string, string>): string {
  if (iri.startsWith('urn:vg:bnode:')) return `_:${iri.slice('urn:vg:bnode:'.length)}`;
  for (const [prefix, uri] of Object.entries(prefixes)) {
    if (uri && iri.startsWith(uri)) return `${prefix}:${iri.slice(uri.length)}`;
  }
  return iri.split(/[/#]/).pop() ?? iri;
}
