// What one TypeScript module reaches for (DESIGN 5, the reference check).
//
//     node refs.mjs <module.ts> <rolldown/dist/parse-ast-index.mjs>
//
// Prints one JSON line:
//     {"imports": [specifiers], "forbidden": [what it may not use]}
//     {"error": "..."}            the file does not parse (the tests will say so)
//
// A module of the design is a pure function of its arguments: the clock, the
// randomness, the screen, the network and storage belong to the platform's
// shell, which calls the module and passes in what it needs. So the globals a
// module may use are listed -- the language's own tools for computing -- and
// everything else is refused. A list of what is allowed, not of what is not:
// a list of what is not misses whatever nobody thought of.
//
// Which imports are allowed depends on the design (a module may import the
// types and the modules it depends on); that check is the adapter's
// (emit.check_references). This file only reports the specifiers. A bare
// specifier ("three", "node:fs") is never a module of the design, so it is
// refused here.
//
// Read with a parser, not a pattern: the one rolldown carries in the frozen
// toolchain. The file is parsed, never run.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const ALLOWED = new Set([
  "undefined", "NaN", "Infinity", "arguments",
  "Math", "JSON", "Number", "String", "Boolean", "BigInt", "Symbol",
  "Array", "Object", "Map", "Set", "WeakMap", "WeakSet",
  "Int8Array", "Uint8Array", "Uint8ClampedArray", "Int16Array", "Uint16Array",
  "Int32Array", "Uint32Array", "Float32Array", "Float64Array", "BigInt64Array", "BigUint64Array",
  "Error", "TypeError", "RangeError", "ReferenceError", "SyntaxError", "EvalError", "URIError", "AggregateError",
  "parseInt", "parseFloat", "isNaN", "isFinite",
  "encodeURIComponent", "decodeURIComponent", "encodeURI", "decodeURI",
]);
// Reachable through an allowed global, and not allowed: a value that changes
// from call to call, or the way back to the Function constructor (eval).
const FORBIDDEN_MEMBERS = { Math: new Set(["random"]) };
const FORBIDDEN_PROPERTIES = new Set(["constructor", "__proto__"]);

// TypeScript nodes that are only types are skipped; these carry a runtime
// expression, which is walked.
const RUNTIME_TS = new Set(["TSAsExpression", "TSSatisfiesExpression", "TSNonNullExpression",
  "TSTypeAssertion", "TSInstantiationExpression", "TSEnumDeclaration", "TSEnumBody", "TSEnumMember",
  "TSParameterProperty", "TSExportAssignment", "TSModuleDeclaration", "TSModuleBlock"]);
const TYPE_KEYS = new Set(["typeAnnotation", "returnType", "typeParameters", "typeArguments",
  "superTypeArguments", "superTypeParameters", "implements", "decorators"]);

function children(node) {
  const out = [];
  for (const [key, value] of Object.entries(node)) {
    if (TYPE_KEYS.has(key)) continue;
    if (Array.isArray(value)) {
      for (const v of value) if (v && typeof v.type === "string") out.push([key, v]);
    } else if (value && typeof value.type === "string") {
      out.push([key, value]);
    }
  }
  return out;
}

function walk(node, visit, parent = null, key = null) {
  if (node.type.startsWith("TS") && !RUNTIME_TS.has(node.type)) return;
  if (visit(node, parent, key) === false) return;
  for (const [k, child] of children(node)) walk(child, visit, node, k);
}

function patternNames(p, into) {
  if (!p) return;
  switch (p.type) {
    case "Identifier": into.add(p.name); break;
    case "ObjectPattern": for (const q of p.properties) patternNames(q.type === "RestElement" ? q.argument : q.value, into); break;
    case "ArrayPattern": for (const q of p.elements) patternNames(q, into); break;
    case "AssignmentPattern": patternNames(p.left, into); break;
    case "RestElement": patternNames(p.argument, into); break;
    case "TSParameterProperty": patternNames(p.parameter, into); break;
  }
}

// Every name the file declares, anywhere. A name declared in one place and
// used as a global in another is not caught; that takes intent, and a pure
// module has nothing to gain by it -- the page's CSP is the second wall.
function bindings(program) {
  const names = new Set();
  walk(program, (n) => {
    switch (n.type) {
      case "VariableDeclarator": patternNames(n.id, names); break;
      case "FunctionDeclaration": case "FunctionExpression": case "ArrowFunctionExpression":
        if (n.id) names.add(n.id.name);
        for (const p of n.params) patternNames(p, names);
        break;
      case "ClassDeclaration": case "ClassExpression": if (n.id) names.add(n.id.name); break;
      case "CatchClause": patternNames(n.param, names); break;
      case "ImportSpecifier": case "ImportDefaultSpecifier": case "ImportNamespaceSpecifier":
        names.add(n.local.name); break;
      case "TSEnumDeclaration": case "TSModuleDeclaration": if (n.id && n.id.name) names.add(n.id.name); break;
    }
  });
  return names;
}

function isReference(parent, key) {
  if (!parent) return true;
  switch (parent.type) {
    case "MemberExpression": return key !== "property" || parent.computed;
    case "Property": case "MethodDefinition": case "PropertyDefinition": case "AccessorProperty":
      return key !== "key" || parent.computed;
    case "LabeledStatement": case "BreakStatement": case "ContinueStatement": return key !== "label";
    case "ImportSpecifier": case "ImportDefaultSpecifier": case "ImportNamespaceSpecifier": return false;
    case "ExportSpecifier": return key === "local";
    case "MetaProperty": return false;
    case "TSEnumMember": return key !== "id";
    case "VariableDeclarator": return key !== "id";
    case "FunctionDeclaration": case "FunctionExpression": case "ArrowFunctionExpression":
      return key === "body";
    case "ClassDeclaration": case "ClassExpression": return key !== "id";
    case "CatchClause": return key !== "param";
    case "TSEnumDeclaration": case "TSModuleDeclaration": return key !== "id";
  }
  return true;
}

// `(Math as any)[k]` is Math[k]: type wrappers do not change the value.
function unwrap(e) {
  while (e && ["TSAsExpression", "TSSatisfiesExpression", "TSNonNullExpression", "TSTypeAssertion",
               "ParenthesizedExpression"].includes(e.type)) e = e.expression;
  return e;
}

function propertyName(member) {
  if (!member.computed && member.property.type === "Identifier") return member.property.name;
  if (member.computed && member.property.type === "Literal" && typeof member.property.value === "string") {
    return member.property.value;
  }
  return null;        // computed from something else: unknown
}

function inspect(program) {
  const declared = bindings(program);
  const imports = [];
  const forbidden = new Set();
  const free = (name) => !declared.has(name);

  walk(program, (n, parent, key) => {
    switch (n.type) {
      case "ImportDeclaration":
        imports.push(n.source.value);
        return false;
      case "ExportAllDeclaration":
        imports.push(n.source.value);
        return false;
      case "ExportNamedDeclaration":
        if (n.source) { imports.push(n.source.value); return false; }
        break;
      case "ImportExpression":
        forbidden.add("import()");
        break;
      case "MemberExpression": {
        const name = propertyName(n);
        const object = unwrap(n.object);
        if (name !== null && FORBIDDEN_PROPERTIES.has(name)) forbidden.add(`.${name}`);
        if (object.type === "Identifier" && free(object.name) && object.name in FORBIDDEN_MEMBERS) {
          if (name === null) forbidden.add(`${object.name}[...]`);
          else if (FORBIDDEN_MEMBERS[object.name].has(name)) forbidden.add(`${object.name}.${name}`);
        }
        break;
      }
      case "VariableDeclarator": {
        // const { random } = Math
        const init = unwrap(n.init);
        if (init && init.type === "Identifier" && free(init.name) && init.name in FORBIDDEN_MEMBERS
            && n.id.type === "ObjectPattern") {
          for (const p of n.id.properties) {
            const k = p.type === "Property" && !p.computed && p.key.type === "Identifier" ? p.key.name : null;
            if (k === null || FORBIDDEN_MEMBERS[init.name].has(k)) forbidden.add(`${init.name}.${k ?? "[...]"}`);
          }
        }
        break;
      }
      case "Identifier":
        if (isReference(parent, key) && free(n.name) && !ALLOWED.has(n.name)) forbidden.add(n.name);
        break;
    }
  });

  for (const spec of imports) if (!spec.startsWith(".")) forbidden.add(`import ${spec}`);
  return { imports: imports.filter((s) => s.startsWith(".")), forbidden: [...forbidden].sort() };
}

const [file, parser] = process.argv.slice(2);
const { parseAst } = await import(pathToFileURL(parser).href);
let program;
try {
  program = parseAst(readFileSync(file, "utf8"), { lang: "ts" }, file);
} catch (e) {
  console.log(JSON.stringify({ error: String((e && e.message) || e).slice(0, 500) }));
  process.exit(0);
}
console.log(JSON.stringify(inspect(program)));
