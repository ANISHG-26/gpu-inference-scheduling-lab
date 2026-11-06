// Real, bounded console recording. Raw captures stay private until reviewed.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { validateTarget, readyPodUid, verifyMeasured } from './policy.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const { baseUrl, revision } = validateTarget(process.argv[2], process.argv[3]);
const capture = path.join(root, '.lab', 'guide-captures', new Date().toISOString().replace(/[:.]/g, '-'));
await mkdir(capture, { recursive: true });
const report = { captured_at: new Date().toISOString(), deployed_source: revision, passed: false, experiments: [] };
let browser, context, page;
const watchdog = setTimeout(() => { browser?.close().catch(() => {}); }, 180_000);
const css = `
/* Recording presentation only: APIs and measured values are unchanged. */
.table-wrap th:nth-child(-n+3), .table-wrap td:nth-child(-n+3) { display:none !important; }
.page-footer { padding-bottom:125px; }
#guide-caption { position:fixed; z-index:10000; bottom:18px; left:24px; right:24px;
  padding:18px 24px; border-radius:12px; background:#102f3f; color:white;
  font:600 23px/1.4 system-ui,sans-serif; box-shadow:0 4px 22px #0004; }
`;
try {
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext({ viewport: { width: 1280, height: 960 },
    recordVideo: { dir: capture, size: { width: 1280, height: 960 } }, reducedMotion: 'reduce' });
  context.setDefaultTimeout(12_000);
  // CSS arrives before the first rendered state, so identifiers cannot flash.
  await context.route(new URL('/style.css', baseUrl).href, async route => {
    const original = await route.fetch({ timeout: 10_000 });
    await route.fulfill({ response: original, body: await original.text() + css });
  });
  page = await context.newPage();
  const state = async () => {
    const response = await context.request.get(new URL('/api/state', baseUrl).href, { timeout: 10_000 });
    assert.equal(response.status(), 200, 'State request must succeed');
    const value = await response.json();
    (report.states ??= []).push(value); // private only; never promoted to videos/.
    return value;
  };
  const initial = await state();
  const uid = readyPodUid(initial);
  assert.notEqual(initial.experiment?.state, 'running', 'Do not interrupt an existing experiment');
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  await page.locator('#connection-text').getByText('Connected · state current', { exact: true }).waitFor();
  await page.evaluate(() => { const caption = document.createElement('div'); caption.id = 'guide-caption'; document.body.append(caption); });
  const caption = async (text, seconds = 6) => {
    await page.locator('#guide-caption').evaluate((element, text) => { element.textContent = text; }, text);
    await page.waitForTimeout(seconds * 1000); // intentional caption reading time
  };
  await page.getByRole('button', { name: /^04 Triton: model repositories and batching/ }).click();
  await caption('Live CPU lesson: predict → run → inspect. This is a real Triton service, not a simulation.');
  await caption('Select the active lesson. Prepared, deployed and measured describe different levels of evidence.');
  await page.locator('.observation-card').scrollIntoViewIfNeeded();
  await caption('Ready pods and placement come from Kubernetes. Raw pod and node identifiers are hidden in this public recording.');
  await page.locator('#prediction').fill('Eight inputs at batch size 1 need eight requests. Batch size 4 should need two requests; both should complete eight inputs.');
  await page.locator('.prediction-card').scrollIntoViewIfNeeded();
  await caption('Prediction: change only client batch size. Keep concurrency at 4 and the same eight input items.');

  for (const batchSize of [1, 4]) {
    readyPodUid(await state(), uid);
    await page.getByLabel('Concurrency', { exact: true }).selectOption('4');
    await page.getByLabel('Batch size', { exact: true }).selectOption(String(batchSize));
    await page.locator('#run-button').scrollIntoViewIfNeeded();
    await caption(`Batch size ${batchSize}: eight input items in ${8 / batchSize} HTTP requests. The model and version stay fixed.`);
    const acceptedPromise = page.waitForResponse(r => r.url() === new URL('/api/experiments', baseUrl).href && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Run 8 input items', exact: true }).click();
    const accepted = await acceptedPromise;
    assert.equal(accepted.status(), 202, 'The operator must admit this exact experiment');
    const admission = await accepted.json();
    assert.equal(typeof admission.id, 'string');
    let completed;
    const deadline = Date.now() + 50_000;
    while (Date.now() < deadline) {
      const current = await state();
      readyPodUid(current, uid);
      if (current.experiment?.id === admission.id && current.experiment.state !== 'running') { completed = current; break; }
      await page.waitForTimeout(500);
    }
    assert.ok(completed, 'Experiment must finish within its bounded observation window');
    const summary = verifyMeasured(completed, { id: admission.id, concurrency: 4, batchSize, uid });
    report.experiments.push(summary);
    await page.locator('#experiment-result').getByText('Experiment measured', { exact: true }).waitFor();
    await page.locator('#experiment-result .result-heading').filter({ hasText: `batch size ${batchSize} ·` }).waitFor();
    assert.equal(await page.locator('#experiment-result .metric').filter({ hasText: 'Requests completed' }).locator('strong').innerText(), String(8 / batchSize));
    await page.locator('#experiment-result').evaluate(element => window.scrollTo({ top: window.scrollY + element.getBoundingClientRect().top - 100 }));
    await caption(`Observed: 8 completed inputs, ${8 / batchSize} successful requests, ${summary.execution_count} backend executions. No valid-request errors.`, 8);
  }
  await caption('HTTP 400 and 404 are expected negative probes: invalid shape and missing version. They are separate from successful inference.', 8);
  await page.screenshot({ path: path.join(capture, 'poster.jpg'), type: 'jpeg', quality: 90 });
  await caption('Requests group input items. Triton may combine requests into executions. Compare counters; these tiny CPU runs are not performance recommendations.', 9);
  report.passed = true;
} catch (error) {
  report.failure = error instanceof assert.AssertionError ? 'A recording acceptance assertion failed' : 'Recording could not complete';
  report.failure_detail = { name: error?.name, message: error?.message }; // private diagnostic only
  process.exitCode = 1;
} finally {
  clearTimeout(watchdog);
  const video = page?.video();
  await context?.close(); // Playwright finalizes video on context closure.
  if (video) await video.saveAs(path.join(capture, 'triton-batching.webm'));
  await browser?.close();
  await writeFile(path.join(capture, 'capture-private.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ passed: report.passed, private_capture: capture, experiments: report.experiments }));
}
