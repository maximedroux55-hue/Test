// A real browser opening the real pages, at a phone width and a desktop width.
//
// This exists because of a bug the Python tests could not have caught. Wrapping
// the "+" button in a span for the desktop layout moved it one level deeper in
// the DOM, and the edit panel, which found its row by counting parents, opened
// with no company and every field blank. Nothing threw. Desktop screenshots
// looked fine because the panel was never opened in them.
//
// So: every page, both widths, and actually click things.
//
//   node tests/browser_check.js            (after regenerating output/*.html)
//
// Exits non-zero on the first failure, and says which page and which width.

const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const path = require('path');
const fs = require('fs');

const OUT = path.resolve(__dirname, '..', 'output');
const PAGES = [
  { file: 'archive.html', name: 'database', editable: true },
  { file: 'held.html',    name: 'held back', editable: true },
  { file: 'news.html',    name: 'all Swiss news', editable: false },
  { file: 'plan.html',    name: 'shortlist', editable: false, picker: true },
];
const WIDTHS = [
  { w: 390,  h: 844, label: 'phone' },
  { w: 1440, h: 900, label: 'desktop' },
];

const problems = [];
function check(cond, where, what) {
  if (!cond) problems.push(`${where}: ${what}`);
  return cond;
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });

  // The database job writes archive, held and news; the posts job writes the
  // shortlist. One run's output directory never holds all four, so a page that
  // this run did not build is skipped out loud rather than failed.
  const built = PAGES.filter(p => fs.existsSync(path.join(OUT, p.file)));
  const missing = PAGES.filter(p => !built.includes(p)).map(p => p.file);
  if (missing.length) console.log(`not built by this run, skipped: ${missing.join(', ')}`);
  if (!built.length) { console.error('FAILED\n  no pages to check at all'); process.exit(1); }

  for (const page of built) {
    for (const size of WIDTHS) {
      const where = `${page.name} @ ${size.label}`;
      const tab = await browser.newPage({ viewport: { width: size.w, height: size.h } });
      const errors = [];
      tab.on('pageerror', e => errors.push(e.message));
      tab.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

      await tab.goto('file://' + path.join(OUT, page.file));
      await tab.waitForTimeout(200);

      // Nothing may scroll the page sideways, on any device.
      const sideways = await tab.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 1);
      check(!sideways, where, 'the page scrolls sideways');

      // Something has to be on the page.
      const rows = await tab.evaluate(
        () => document.querySelectorAll('#rows tr, #rows li, .card').length);
      check(rows > 0, where, 'no rows rendered at all');

      // Filtering has to actually filter.
      const search = await tab.$('#q');
      if (search) {
        await tab.fill('#q', 'zzzznotathing');
        const left = await tab.evaluate(() => [...document.querySelectorAll('#rows tr, #rows li')]
          .filter(r => r.style.display !== 'none').length);
        check(left === 0, where, `search matched ${left} rows on a nonsense query`);
        await tab.fill('#q', '');
      }

      // The edit panel: open it on a real row and read the fields back.
      if (page.editable) {
        const btn = await tab.$('button.fix');
        check(btn !== null, where, 'no edit button on any row');
        if (btn) {
          const company = await tab.evaluate(
            () => document.querySelector('button.fix').closest('tr').dataset.company);
          await btn.click();
          await tab.waitForTimeout(150);
          const state = await tab.evaluate(() => ({
            title: document.getElementById('sheettitle').textContent,
            filled: [...document.querySelectorAll('#fields input')].filter(i => i.value).length,
            boxes: document.querySelectorAll('#fields input').length,
            saveOff: document.getElementById('savebtn').disabled,
          }));
          check(state.title === company, where,
                `panel title is "${state.title}", expected "${company}"`);
          check(state.boxes > 0, where, 'the panel rendered no fields');
          check(state.filled > 0, where,
                'every field in the panel is blank, so the row was never found');
          check(state.saveOff, where, 'Save is enabled before anything was typed');

          // Typing must enable Save, and Save must be reachable without hunting.
          await tab.fill('#f_website', 'example.ch');
          const after = await tab.evaluate(() => {
            const b = document.getElementById('savebtn');
            const r = b.getBoundingClientRect();
            return { off: b.disabled, onScreen: r.top >= 0 && r.bottom <= window.innerHeight + 1 };
          });
          check(!after.off, where, 'Save stayed disabled after typing');
          check(after.onScreen, where, 'Save is off screen when the panel is open');
        }
      }

      // The shortlist: ticking cards has to build an instruction naming those
      // cards and no others, on working days only.
      if (page.picker) {
        check(await tab.evaluate(() => document.getElementById('copybtn').disabled),
              where, 'Copy is enabled before anything is picked');
        const want = await tab.evaluate(() => {
          var all = [].slice.call(document.querySelectorAll('.card'));
          // Two cards that are not the first, so a leak is visible.
          return all.slice(1).filter((_, i) => i % 2 === 0).slice(0, 2)
                    .map(c => c.dataset.index);
        });
        for (const n of want) await tab.click(`.card[data-index="${n}"] .tick`);
        const state = await tab.evaluate(() => ({
          off: document.getElementById('copybtn').disabled,
          lit: document.querySelectorAll('.card.chosen').length,
          text: instruction(),
          all: [].slice.call(document.querySelectorAll('.card'))
                 .map(c => c.dataset.index),
        }));
        check(!state.off, where, 'Copy stayed disabled after picking');
        check(state.lit === want.length, where,
              `${state.lit} cards highlighted, expected ${want.length}`);
        for (const n of want)
          check(state.text.includes(`- post ${n} on `), where,
                `picked post ${n} is missing from the instruction`);
        for (const n of state.all.filter(n => !want.includes(n)))
          check(!state.text.includes(`- post ${n} on `), where,
                `post ${n} was not picked but reached the instruction`);
        check(!/(Saturday|Sunday)/.test(state.text), where,
              'a picked post was scheduled on a weekend');
        await tab.click('#clearbtn');
        check(await tab.evaluate(
                () => document.querySelectorAll('.card.chosen').length) === 0,
              where, 'Clear left cards highlighted');
      }

      check(errors.length === 0, where, `console errors: ${errors.join(' | ')}`);
      await tab.close();
    }
  }

  await browser.close();

  if (problems.length) {
    console.error('FAILED\n  ' + problems.join('\n  '));
    process.exit(1);
  }
  console.log(`all pages pass, ${built.length} pages x ${WIDTHS.length} widths`);
})();
