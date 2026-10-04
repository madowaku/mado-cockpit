import { chromium } from 'playwright';

async function main() {
  const baseUrl = process.env.MADO_E2E_BASE_URL ?? 'http://127.0.0.1:4310';
  const operatorId = process.env.MADO_E2E_OPERATOR_ID;
  const evidenceDir = process.env.MADO_E2E_EVIDENCE_DIR ?? '.mado-e2e';

  if (!operatorId) throw new Error('MADO_E2E_OPERATOR_ID is required.');

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  try {
    await page.goto(
      `${baseUrl}/mado-dogfood?operator_id=${encodeURIComponent(operatorId)}`,
      { waitUntil: 'networkidle' },
    );

    await page.getByText('Human decision required').waitFor();
    await page.getByText('Enable the paid provider for this run?').waitFor();
    await page.getByText('awaiting_human').first().waitFor();

    await page.screenshot({
      path: `${evidenceDir}/01-human-gate-open.png`,
      fullPage: true,
    });

    await page.getByRole('button', { name: /stay_free/i }).click();

    await page
      .getByText('Human Gate cleared. Cockpit resumed at awaiting_builder.')
      .waitFor();
    await page.getByText('awaiting_builder').first().waitFor();

    const status = await page.evaluate(async (id) => {
      const response = await fetch(
        `/api/mado-dogfood/status?operator_id=${encodeURIComponent(id)}`,
      );
      return await response.json();
    }, operatorId);

    if (
      !status ||
      status.ok !== true ||
      status.data?.status !== 'awaiting_builder' ||
      status.data?.human_gate !== null
    ) {
      throw new Error(
        `Unexpected final Cockpit state: ${JSON.stringify(status)}`,
      );
    }

    await page.screenshot({
      path: `${evidenceDir}/02-human-gate-resolved.png`,
      fullPage: true,
    });

    console.log(
      JSON.stringify(
        {
          ok: true,
          operator_id: operatorId,
          initial_status: 'awaiting_human',
          choice: 'stay_free',
          final_status: status.data.status,
          human_gate: status.data.human_gate,
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
}

void main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
