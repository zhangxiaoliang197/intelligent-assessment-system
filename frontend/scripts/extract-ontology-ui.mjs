import ts from '../ontosphere/node_modules/typescript/lib/typescript.js';
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { translateUi } from '../ontosphere/src/integration/translations-zh.ts';
const root = resolve('ontosphere/src');
const found = new Map();
function scan(dir) {
 for (const entry of readdirSync(dir, {withFileTypes:true})) {
  const path = resolve(dir,entry.name);
  if (entry.isDirectory()) { if (entry.name !== '__tests__' && entry.name !== 'ui') scan(path); continue; }
  if (!/\.tsx?$/.test(entry.name) || /\.test\./.test(entry.name)) continue;
  const code=readFileSync(path,'utf8'), source=ts.createSourceFile(path,code,ts.ScriptTarget.Latest,true,entry.name.endsWith('tsx')?ts.ScriptKind.TSX:ts.ScriptKind.TS);
  function visit(node) {
   let value;
   if(ts.isJsxText(node)) value=node.text.replace(/\s+/g,' ').trim();
   else if(ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
    const p=node.parent;
    if(ts.isJsxAttribute(p) && ['title','placeholder','aria-label','alt'].includes(p.name.getText(source))) value=node.text;
    else if(ts.isPropertyAssignment(p) && /^(label|title|description|placeholder|message|heading|tooltip)$/.test(p.name.getText(source))) value=node.text;
    else if((path.includes('components') || path.includes('hooks')) && /[A-Z]/.test(node.text[0] || '') && !/^(import|http|urn:|\.|#)/.test(node.text) && !ts.isImportDeclaration(p)) value=node.text;
   }
   if(value && /[a-zA-Z]{2}/.test(value) && !/[\u4e00-\u9fff]/.test(value) && value.length<1200 && !/^[.#@/]|^--|^[A-Z_]+$/.test(value) && !/^[a-z\d:!_[\]/.\-\s]+$/.test(value)) found.set(value,(found.get(value)||[]).concat(path.replace(root+'\\','')));
   ts.forEachChild(node,visit);
  }
  visit(source);
 }
}
scan(root);
const values=[...found.keys()].sort();
writeFileSync('../tmp/ontology-ui/english-ui.json',JSON.stringify(Object.fromEntries(values.map(v=>[v,''])),null,2));
console.log(JSON.stringify(values.filter(value => found.get(value).some(file => file.startsWith('components')) && translateUi(value) === value)));
