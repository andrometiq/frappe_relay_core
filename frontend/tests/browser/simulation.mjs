// Run with a Playwright page against the built fixture served on loopback:18120.
export default async (page) => {
 const failures=[]; const errors=[]; const metrics=[];
 const onError=e=>errors.push(e.message); page.on('pageerror',onError);
 try {
 for (const [width,height] of [[1440,900],[768,1024],[390,844],[320,568]]) {
  await page.setViewportSize({width,height});
  await page.goto('http://127.0.0.1:18120/tests/browser/table.html');
  await page.locator('[data-row-id]').first().waitFor();
  let peakRows=0,peakHeight=0;
  for (let i=0;i<22;i++) {
   const before=await page.evaluate(()=>window.testPages);
   await page.getByRole('button',{name:'Load more',exact:true}).click();
   await page.waitForFunction(old=>window.testPages>old,before);
   const stats=await page.evaluate(()=>{
    const el=document.querySelector('[aria-label="Million record fixture rows"]');
    return {rows:el.querySelectorAll('[data-row-id]').length,height:el.scrollHeight};
   });
   peakRows=Math.max(peakRows,stats.rows);peakHeight=Math.max(peakHeight,stats.height);
  }
  const end=await page.locator('[data-row-id]').first().getAttribute('data-row-id');
  await page.getByRole('button',{name:'Load earlier',exact:true}).click();
  await page.waitForFunction(last=>Number(document.querySelector('[data-row-id]').dataset.rowId)<Number(last),end);
  const values=await page.evaluate(()=>({pages:window.testPages,maxPage:window.maxRequested,overflow:document.documentElement.scrollWidth>innerWidth+1}));
  if(peakRows>40 || peakHeight>200*76+100 || values.maxPage>50 || values.overflow) failures.push({width,peakRows,peakHeight,...values});
  metrics.push({width,height,peakRows,peakScrollHeight:peakHeight,...values,reversePaging:true});
 }
 if(errors.length || failures.length) throw new Error(JSON.stringify({errors,failures,metrics}));
 return {passed:true,fixtureRecords:1000000,metrics,errors};
 } finally {page.off('pageerror',onError);}
}

