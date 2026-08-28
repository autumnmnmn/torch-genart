# Webui module conventions

Everything a module needs is a handful of globals defined in
`common/code/core.js` (loaded as a plain script before anything else) plus a
few patterns the existing modules follow. There is no build step, no
framework, and no dependencies: `common/code/*.js` files are ES modules
served directly, and cross-module imports use absolute paths like
`import { greek } from "/code/math/math.js"`.

## The `$mod` lifecycle

A module is any `.js` file under `common/code/` that exports
`async function main(...)`:

```js
export async function main(target, ...args) {
    // build DOM
    return { dom: [rootElement], replace: true };
}
```

Loaders in `core.js`:

- `$mod(name, ...args)` → imports `/code/{name}.js` and calls `main`,
  returns whatever `main` returns.
- `$apply(name, target, ...args)` → appends `result.dom` into `target`.
- `$replace(scriptTag, name, ...args)` → used from inline `<script>` in
  markup pages (`$replace(document.currentScript, "gpu/lyapunov")`); hoists
  the result out of the script's parent and removes the script.
- `$prepMod(name, args)` → returns an async initializer suitable for
  `layout/split`'s `content` array.

The `main` return value:

- `{ dom: [...] }` — the elements to insert. Always an array.
- `replace: true` — tells `$apply`-style callers that the module wants to
  *replace* the slot it was loaded into (the caller removes the original
  element). `layout/nothing` and the debug client do this.
- `inline: true` — opts out of `$replace`'s hoisting.

`main` receives `(target, ...args)` — `target` is whatever the caller
passed (for `$apply` it's the container element; for `$replace` it's the
script tag). Not every module uses it.

## DOM helpers (globals from `core.js`)

- `$element(tag)` — `document.createElement`.
- `$div(className)` — a div with a class.
- `$svgElement(tag)`, `$mathElement(tag)`, `$htmlElement(tag)` —
  namespaced variants.
- `el.$with(...children)` — append children, returns `el` (chainable).
- `el.$attrs` — a proxy for get/set/remove attributes.
- `$actualize(maybeFn)` — call it if it's a function, else return as-is
  (used for lazily-computed context-menu items).

## Styling

Modules inject their own CSS by calling the global `$css(\`...\`)` with a
template literal — it appends an adopted stylesheet. The convention is one
`$css` call at the top of the file. Custom elements are common (`nothing-`, `split-`,
`divider-`, `portion-`), registered with `customElements.define` right in
the module. Theme values come from CSS variables (`--main-background`,
`--main-faded`, `--main-solid`, `--main-font`, `--panel-margin`), set by
`theme.js`; never hardcode colors.

## Context menus

Right-click menus are assembled by `control/menu.js` walking up the DOM
from the event target, collecting `$contextMenu` properties. To contribute
items, set on your module's root element:

```js
root.$contextMenu = {
    items: [
        ["do a thing", doThing],       // [label, async fn]
        () => maybeItem,               // lazy: return an item, array, or falsy
        "separator",
    ]
};
```

Items are `$actualize`d, so functions that return items are evaluated when
the menu opens (good for dynamic labels like show/hide toggles). Menus from
nested elements accumulate up the chain, unless a node sets
`$contextMenu.override`. The body gets a default menu in `main.js`.

## Exiting a module

The established pattern (see `gpu/lyapunov.js`, `gpu/brot.js`,
`llm/concat.vibe.js`) is an "exit" item in the root's context menu:

```js
function exitTool() {
    // disconnect observers / close sockets / release resources first
    const parent = topmost.parentNode;
    topmost.remove();
    if (parent && !parent.hasChildNodes()) {
        $apply("layout/nothing", parent);
    }
}
```

Remove your root; if that leaves the container empty, refill it with
`layout/nothing`. Clean up everything your module registered (ResizeObservers,
theme observers, websockets, GPU resources) before removing.

## Focus & keyboard

Interactive elements that should participate in directional focus
navigation (see `layout/split.js`) set `el.$ = { focusable: true }` and a
`tabIndex`. Context menus respond to `o`/`Enter` to open, `j`/`k`/arrows to
move, `Escape` to close — match those keys if you add keyboard shortcuts.

## Loading from `layout/nothing`

`layout/nothing` is the empty-slot module and the root of the "nothing
menu" — the context menu on empty space that lists loadable modules. To add
a module to it, add an entry to the `menuItems` object in
`layout/nothing.js`:

```js
const load = (modName, args=[]) => async () => { ... };
// ...
mymodule: load("category/mymodule"),
```

Entries whose `main` returns `replace: true` take over the nothing slot.

## Entry points & file layout

- Markup lives in `common/markup/*.html`; each page loads `/code/core.js`,
  then `/code/main.js` (as `type="module"`), then applies an initial module
  to `document.body` (usually `layout/nothing`).
- `main.js` imports `control/menu.js` (installs the global contextmenu
  handler) and applies the theme.
- Sites under `webui/sites/` compose the common pieces.

## Conventions checklist for a new module

1. `$css` block at top if you need styles; use theme variables.
2. `export async function main(target, ...)` returning `{ dom: [...] }`
   (add `replace: true` if it should own its slot).
3. Root element gets `$contextMenu` with at least `["exit", exitTool]` if
   the module is a self-contained tool.
4. `exitTool` releases resources and replaces itself with `layout/nothing`.
5. If it's user-loadable, register it in `layout/nothing.js`'s menu.
