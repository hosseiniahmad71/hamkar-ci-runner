/* P49 external CI: synthetic-only Chromium smoke of REAL private frontend build. */
'use strict';
const assert=require('node:assert/strict');
const path=require('node:path');
let chromium;
try{({chromium}=require(require.resolve('@playwright/test',{paths:[process.cwd()]})))}catch(error){console.log('P49_CHROMIUM_FAIL_CLASS=P49_IMPORT_DEPENDENCY');process.exit(1)}

let syntheticRouteFault='';
async function run(){
 const state={revision:7,scope:'ISOLATED_PREVIEW',updated_at:'2026-10-16T00:00:00Z',
   products:[],stock_movements:[],catalog:{cats:[],subcats:[],brands:[],shared_params:{},subcat_params:{}},
   settings:{toman_rounding:'ceil'},bundles:[]};
 const panel={panel_id:'first',name:'غرفه ساختگی',vendor_title:'غرفه ساختگی',vendor_id:'44',
   last_verified_at:'2026-10-16T12:00:00Z',connection:'VERIFIED',message:'',pending_products:[],parent_pending_products:[]};
 const field=(key,value,unit='TEXT')=>({key,value,unit,label:key});
 const row={id:'31',title:'کالای ساختگی با عنوان طولانی برای تست چیدمان نسخهٔ P49',sku:null,
   detail_source:'API_DETAIL',received_at:'2026-10-16T00:00:00Z',images:[],url:null,
   description:'آزمون بدون ارتباط واقعی',external_product_id:'31',external_variant_id:null,
   price:{value:'3600000',unit:'IRR'},
   fields:[field('general_contract','P49'),field('has_variation','بله'),field('variant_count','2','COUNT'),
     field('status_code','2976'),field('inventory','8','COUNT'),field('preparation_day','2','COUNT'),
     field('primary_price','4000000','IRR')],
   variations:[{id:'7',label:'رنگ: قرمز - نمونهٔ ساختگی',primary_price:'4000000',price:'3600000',stock:'8',sku:'RED',
     editable_fields:['primary_price','stock','sku'],pending:false},
     {id:'8',label:'رنگ: آبی - نمونهٔ ساختگی',primary_price:'5000000',price:'4500000',stock:'4',sku:'BLUE',
     editable_fields:['primary_price','stock','sku'],pending:false}]};
 const pricing={revision:7,rows:{'31':{
   automation:{enabled:false,unit:'weeks',interval:1,next_due:null},
   economics:{current_profit_toman:'12450',current_profit_pct:'12.2'},
   sale_toman:'360000',original_toman:'400000',discount_pct:'10'}}};
 const writes=[],errors=[];
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 const page=await browser.newPage({viewport:{width:390,height:900}});
 try{
   page.on('pageerror',e=>errors.push(e.name));
   await page.route(/^https:\/\/(?!127\.0\.0\.1)/,route=>route.abort());
   await page.route('**/__erp_preview/**',async route=>{
     try{
     const req=route.request(),key=new URL(req.url()).pathname.replace('/__erp_preview/','');let body;
     if(key==='state')body=state;
     else if(key==='about')body={runtime_source_sha:'SYNTHETIC',frontend_source_sha:null,python:'test',packages:{}};
     else if(key==='private-inventory')body={loaded:false,products:[],total:0};
     else if(key==='platforms/basalam')body={panels:[panel]};
     else if(key==='bundle-products')body={products:[],selectable_ids:[]};
     else if(key==='basalam-pricing/catalog')body=pricing;
     else if(key==='basalam-pricing')body={history:[],revision:state.revision,config:{default_commission:'6.5',default_profit:'50',default_packaging:'10000',weekly:false,use_tariff:true,products:{}},tariff:{rows:844,rate_groups:23,version:'1405-07'}};
     else if(key==='platforms/basalam/store')body={panel,cache:{scope_id:'synthetic-scope',provider:'basalam',panel_id:'first',vendor_id:'44',
       pages:{'1':{page:1,total_pages:1,rows:[row],received_count:1,catalog_policy:'basalam-products-v2'}},
       details:{'31':row},orders:{}},links:[],revision:state.revision};
     else if(key==='platforms/basalam/products')body={products:{page:1,total_pages:1,rows:[row],catalog_policy:'basalam-products-v2'}};
     else if(key==='platforms/basalam/detail')body={detail:row};
     else if(key==='platforms/basalam/edit-variation'){
       const sent=req.postDataJSON();writes.push(sent);
       assert.equal(sent.product_id,'31');assert.equal(sent.variation_id,'7');
       assert.deepEqual(JSON.parse(sent.changes),{primary_price:4100000});
       assert.deepEqual(JSON.parse(sent.expected),{primary_price:4000000});
       row.variations[0].primary_price='4100000';
       body={detail:row,edit_verified:true,variation_id:'7'};
     } else {
       syntheticRouteFault='P49_UNEXPECTED_API';
       body={};
     }
     await route.fulfill({json:body});
     }catch(error){
       syntheticRouteFault='P49_SYNTHETIC_ROUTE_FAILURE';
       try{await route.fulfill({status:500,json:{detail:'Synthetic test fixture error'}})}catch{/* response may already be sent */}
     }
   });
   await page.goto('http://127.0.0.1:4177/#marketplaces/basalam/first');
   await page.locator('.bs-catalog-finance .bs-profit-value').waitFor({timeout:15000});
   for(const width of [320,390,768]){
     await page.setViewportSize({width,height:900});
     const check=await page.locator('.bs-profit-value').first().evaluate(el=>{
       const rows=[...el.children].map(e=>e.getBoundingClientRect());
       const amount=getComputedStyle(el.children[1]).color,percent=getComputedStyle(el.children[2]).color;
       return {overflow:document.documentElement.scrollWidth>innerWidth+1,
         rowCount:rows.length,ordered:rows[1].top>=rows[0].bottom-1&&rows[2].top>=rows[1].bottom-1,
         different:amount!==percent,labels:el.textContent||''};
     });
     assert.equal(check.overflow,false,'P49_CARD_OVERFLOW_'+width);
     assert.equal(check.rowCount,3,'P49_PROFIT_ROW_COUNT');
     assert.ok(check.ordered,'P49_PROFIT_ROW_OVERLAP_'+width);
     assert.ok(check.different,'P49_PROFIT_COLOR');
     assert.ok(check.labels.includes('مبلغ:')&&check.labels.includes('درصد:'),'P49_PROFIT_LABELS');
   }
   await page.goto('http://127.0.0.1:4177/#marketplaces/basalam/first/product/31');
   await page.locator('.bs-variation-item[data-variation-id="7"]').waitFor({timeout:15000});
   assert.equal(await page.locator('.bs-variation-item').count(),2,'P49_VARIANT_COUNT');
   for(const width of [320,390,768]){
     await page.setViewportSize({width,height:1000});
     const check=await page.locator('.bs-variation-item').first().evaluate(el=>{
       const list=[...el.querySelectorAll('.bs-variation-fields label')].map(x=>x.getBoundingClientRect());
       const intersects=(a,b)=>a.left<b.right-1&&b.left<a.right-1&&a.top<b.bottom-1&&b.top<a.bottom-1;
       return {overflow:document.documentElement.scrollWidth>innerWidth+1,overlaps:list.some((a,i)=>list.slice(i+1).some(b=>intersects(a,b)))};
     });
     assert.equal(check.overflow,false,'P49_VARIANT_OVERFLOW_'+width);
     assert.equal(check.overlaps,false,'P49_VARIANT_FIELDS_OVERLAP_'+width);
   }
   page.on('dialog',d=>d.accept());
   await page.getByLabel('قیمت اصلی تنوع 7').fill('410000');
   await page.locator('.bs-variation-item[data-variation-id="7"] button.primary').click();
   await page.waitForTimeout(500);
   assert.equal(writes.length,1,'P49_VARIATION_ONE_PATCH');
   assert.equal(writes[0].product_id,'31');
   assert.equal(errors.length,0,'P49_BROWSER_PAGEERROR');
   console.log('P49_CHROMIUM_PASS widths=320,390,768 profit_rows=3 variations=2 sparse_patch=1');
 } finally {await browser.close();}
}
run().catch(error=>{const label=syntheticRouteFault||(/^P49_[A-Z0-9_]+$/.test(String(error.message))?error.message:'P49_BROWSER_UNKNOWN');console.log('P49_CHROMIUM_FAIL_CLASS='+label);process.exitCode=1;});
