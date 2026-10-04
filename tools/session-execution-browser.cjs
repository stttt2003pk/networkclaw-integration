// 浏览器仅使用隔离夹具账号；证据不保存请求正文、cookie 或 transcript。
const fs = require('node:fs');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
  try {
    const page = await browser.newPage();
    const requests = [];
    let created = 0;
    page.on('request', request => {
      const url = new URL(request.url());
      requests.push(url.pathname);
      if (request.method() === 'POST' && url.pathname === '/api/v1/sessions') {
        const body = request.postDataJSON();
        if (Object.keys(body).length) throw new Error('ordinary_create_contains_preset');
        created++;
      }
    });
    await page.goto(process.env.SESSION_EXECUTION_BROWSER_URL);
    await page.locator('input[autocomplete="username"]').fill('model-admin');
    await page.locator('input[type="password"]').fill('model-admin-fixture-password');
    await page.getByRole('button', { name: /^(登录|Sign in)$/ }).click();
    const input = page.locator('textarea');
    await input.waitFor();
    const models = JSON.parse(process.env.SESSION_EXECUTION_BROWSER_MODELS);
    const picker = page.locator('select').filter({ has: page.locator(`option[value="${models[0]}"]`) });
    await picker.selectOption(models[0]);
    for (const [index, model] of models.entries()) {
      await picker.selectOption(model);
      await input.fill(`ordinary-browser-${index}`);
      await input.press('Enter');
      await page.waitForFunction(expected => [...document.querySelectorAll('p')].filter(e => e.textContent === 'interop-ok').length >= expected, index + 1, { timeout: 120000 });
      await page.waitForFunction(() => !document.querySelector('textarea').disabled);
    }
    if (created !== 1) throw new Error('browser_did_not_reuse_session');
    if (requests.some(path => /catalog\/agents|agent-profiles/.test(path))) throw new Error('ordinary_browser_requested_agent_catalog');
    const checks = ['browser_login', 'browser_no_profile_first_send', 'browser_same_session_model_switch', 'browser_no_agent_catalog'];
    fs.writeFileSync(process.env.SESSION_EXECUTION_BROWSER_OUTPUT, JSON.stringify({ status: 'passed', checks, created_sessions: created }));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
