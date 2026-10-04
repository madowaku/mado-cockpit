import { chromium } from 'playwright';

async function main() {
  const baseUrl = process.env.MADO_M1_9_BASE_URL ?? 'http://127.0.0.1:4310';
  const operatorId = process.env.MADO_M1_9_OPERATOR_ID;
  const evidenceDir = process.env.MADO_M1_9_EVIDENCE_DIR ?? '.mado-m1.9';

  if (!operatorId) throw new Error('MADO_M1_9_OPERATOR_ID is required.');

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 980 } });
  const browserErrors: string[] = [];
  const requestFailures: string[] = [];
  const badResponses: string[] = [];

  page.on('pageerror', (error) => browserErrors.push(error.message));
  page.on('requestfailed', (request) =>
    requestFailures.push(
      `${request.method()} ${request.url()} :: ${request.failure()?.errorText ?? 'failed'}`,
    ),
  );
  page.on('response', (response) => {
    if (
      response.status() >= 400 &&
      (response.url().includes('/api/copilotkit') ||
        response.url().includes('/api/conversations'))
    )
      badResponses.push(
        `${response.status()} ${response.request().method()} ${response.url()}`,
      );
  });

  try {
    await page.goto(baseUrl, { waitUntil: 'networkidle' });

    const starter = page.getByRole('textbox', { name: 'Start a conversation' });
    await starter.waitFor();
    await starter.fill(
      `Check MADO mission ${operatorId} and continue safely.`,
    );
    await page.getByRole('button', { name: 'Start conversation' }).click();

    await page.getByText('Human decision required').waitFor();
    await page
      .getByText('Enable the paid provider for this browser chat?')
      .waitFor();
    await page.getByText('Human decision pending').waitFor();

    await page.screenshot({
      path: `${evidenceDir}/01-normal-chat-human-gate.png`,
      fullPage: true,
    });

    await page
      .locator('.mado-gate-choices button')
      .filter({ hasText: 'stay_free' })
      .click();

    await page
      .getByText(
        'Mission resumed on the free path. Cockpit is ready for Builder work.',
      )
      .waitFor();

    await page.screenshot({
      path: `${evidenceDir}/02-normal-chat-resumed.png`,
      fullPage: true,
    });

    if (browserErrors.length)
      throw new Error(`Browser page errors: ${browserErrors.join(' | ')}`);

    console.log(
      JSON.stringify(
        {
          schema: 'mado.opendots.browser-chat-e2e.v1',
          version: 'MCC-M1.9',
          ok: true,
          operator_id: operatorId,
          prompt: `Check MADO mission ${operatorId} and continue safely.`,
          human_choice: 'stay_free',
          final_text:
            'Mission resumed on the free path. Cockpit is ready for Builder work.',
          browser_errors: browserErrors,
        },
        null,
        2,
      ),
    );
  } catch (cause) {
    await page
      .screenshot({
        path: `${evidenceDir}/99-normal-chat-failure.png`,
        fullPage: true,
      })
      .catch(() => undefined);
    const bodyText = await page
      .locator('body')
      .innerText()
      .catch(() => '<body unavailable>');
    const alerts = await page
      .getByRole('alert')
      .allTextContents()
      .catch(() => []);
    console.error(
      JSON.stringify(
        {
          schema: 'mado.opendots.browser-chat-diagnostic.v1',
          operator_id: operatorId,
          browser_errors: browserErrors,
          request_failures: requestFailures,
          bad_responses: badResponses,
          alerts,
          body_text: bodyText.slice(0, 12000),
        },
        null,
        2,
      ),
    );
    throw cause;
  } finally {
    await browser.close();
  }
}

void main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
