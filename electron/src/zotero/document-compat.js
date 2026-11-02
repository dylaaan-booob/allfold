'use strict';
// Snapshot-only semantic aliases; do not patch upstream Translator internals.
globalThis.LiteratureDocumentCompat={
  normalize(doc) {
    const canonical=uri=>uri.replace(/^https?:\/\/purl\.org\/(?:DC|dc)\/elements\/(1\.[01])\/$/,
      'http://purl.org/dc/elements/$1/');
    for(const link of doc.querySelectorAll('link[rel][href]'))
      if(/^schema\./i.test(link.getAttribute('rel')))
        link.setAttribute('href',canonical(link.getAttribute('href')));
    for(const node of [doc.documentElement,doc.head])if(node?.hasAttribute('prefix'))
      node.setAttribute('prefix',node.getAttribute('prefix').replace(/(\w+:\s+)(\S+)/g,
        (_match,prefix,uri)=>prefix+canonical(uri)));
    return doc;
  },
  decode(bytes,charset='utf-8') {
    let decoder;try{decoder=new TextDecoder(charset);}catch{decoder=new TextDecoder('utf-8');}
    return decoder.decode(bytes);
  },
  json(text) {try{return JSON.parse(text);}catch{return text;}},
};
