async page => {
  const issues = [];
  page.on('pageerror', e => issues.push(`pageerror: ${e.message}`));
  page.on('console', m => { if (m.type() === 'error') issues.push(`console: ${m.text()}`); });
  await page.setViewportSize({width: 1440, height: 1000});
  await page.goto('http://127.0.0.1:8000');
  await page.waitForSelector('#kpi-aqi');
  await page.waitForFunction(() => document.querySelector('#kpi-aqi')?.textContent !== '—');
  if (!(await page.locator('#station-layer .station-marker').count()) || !(await page.locator('#forecast-chart svg').count())) throw new Error('Overview map or chart missing');
  await page.screenshot({path:'artifacts/screenshots/overview.png'});
  await page.locator('#time-slider').fill('48');
  if ((await page.locator('#hour-readout').textContent()).trim() !== 'T+48:00') throw new Error('Time slider did not update');
  const at48 = await page.locator('#kpi-aqi').textContent();
  await page.screenshot({path:'artifacts/screenshots/overview-48h.png'});
  await page.locator('[data-station="noida-sector-62"]').click();
  if (!(await page.locator('#station-title').textContent()).includes('Noida')) throw new Error('Station detail did not update');
  await page.screenshot({path:'artifacts/screenshots/station-detail.png'});
  for (const [href, needle, filename] of [
    ['#inversion', 'INVERSION & VENTILATION', 'inversion.png'],
    ['#plume', 'SMOKE PLUME TRACKER', 'plume.png'],
    ['#coupling', 'METEOROLOGY ↔ CHEMISTRY COUPLING', 'coupling.png'],
    ['#verify', 'FORECAST VERIFICATION', 'verification.png']
  ]) {
    await page.locator(`a[href="${href}"]`).first().click();
    await page.waitForTimeout(100);
    if (!(await page.locator('#page-title').textContent()).toUpperCase().includes(needle)) throw new Error(`Navigation failed: ${href}`);
    await page.screenshot({path:`artifacts/screenshots/${filename}`});
  }
  await page.locator('.demo-link').click();
  await page.locator('a[href="#whatif"]').click();
  await page.locator('#scenario-slider').fill('50');
  await page.getByRole('button', {name:'Run scenario simulation'}).click();
  await page.waitForFunction(() => document.querySelector('#scenario-status')?.textContent.includes('complete'));
  const delta = await page.locator('#scenario-delta').textContent();
  if (!delta || delta === '0.0') throw new Error('What-if did not change output');
  await page.screenshot({path:'artifacts/screenshots/whatif.png'});
  await page.locator('a[href="#overview"]').first().click();
  await page.setViewportSize({width:375,height:812});
  await page.screenshot({path:'artifacts/screenshots/mobile-overview.png',fullPage:true});
  const mobile = await page.evaluate(() => ({width:innerWidth, scrollWidth:document.documentElement.scrollWidth}));
  if (mobile.scrollWidth > mobile.width + 3) throw new Error(`Mobile overflow ${JSON.stringify(mobile)}`);
  if (issues.length) throw new Error(issues.join('\n'));
  return {status:'passed', at48, station:'Noida Sector 62', scenarioDelta:delta, mobile, consoleErrors:issues.length};
}
