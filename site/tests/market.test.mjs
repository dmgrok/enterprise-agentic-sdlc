import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateSnapshot, eventIndices, change, chartValue, windowIndices } from '../market-model.mjs';
const data=JSON.parse(readFileSync(new URL('../market/deepseek-2025.json',import.meta.url)));
test('recorded prices align across five assets with bounded provenance',()=>{
 assert.equal(validateSnapshot(data),data);
 assert.equal(data.dates.length,19);
 assert.equal(data.dates[0],'2025-01-13');assert.equal(data.dates.at(-1),'2025-02-07');
 for(const mutate of [d=>d.series[0].values[0]=null,d=>d.series[0].values.pop(),d=>d.dates[2]=d.dates[1],d=>d.series[0].symbol='PRIVATE-LAB',d=>d.series[0].source_url='https://query1.finance.yahoo.com.evil.test/data',d=>d.events[0].date='2025-02-30']){
  const value=structuredClone(data);mutate(value);assert.throws(()=>validateSnapshot(value));
 }
});
test('a holiday release uses the previous close and the next actual session',()=>{
 const release=eventIndices(data,'2025-01-20');
 assert.equal(data.dates[release.baseline],'2025-01-17');assert.equal(data.dates[release.first],'2025-01-21');
 assert.equal(data.dates.includes('2025-01-20'),false);
 const reaction=eventIndices(data,'2025-01-27');assert.equal(data.dates[reaction.baseline],'2025-01-24');
});
test('the recorded NVDA sell-off is about 16.97 percent, without extrapolation',()=>{
 const {baseline,first}=eventIndices(data,'2025-01-27'),nvda=data.series.find(s=>s.symbol==='NVDA');
 assert.ok(Math.abs(change(nvda.values[first],nvda.values[baseline])-(-16.97))<.02);
 assert.equal(chartValue(data,nvda,baseline,baseline,'indexed'),100);
});
test('benchmark comparison is a percentage-point difference, not a causal estimate',()=>{
 const fixture={series:[{symbol:'SPY',values:[100,110]}]},asset={values:[50,60]};
 assert.ok(Math.abs(chartValue(fixture,asset,1,0,'relative')-10)<1e-10);
 assert.ok(Math.abs(chartValue(fixture,asset,1,0,'indexed')-120)<1e-10);
 assert.equal(chartValue(fixture,fixture.series[0],1,0,'relative'),0);
});
test('windows clamp to available sessions instead of inventing missing observations',()=>{
 assert.deepEqual(windowIndices(data,'2025-01-27','full'),[0,18]);
 const [lo,hi]=windowIndices(data,'2025-01-27','near');assert.equal(hi-lo,10);
 assert.throws(()=>eventIndices(data,'2025-01-01'));
});
