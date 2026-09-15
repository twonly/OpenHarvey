// Run before the first paint; the account preference is refreshed after login.
(()=>{
 let locale='zh-CN';
 try{
  const entry=new URLSearchParams(location.search).get('lang');
  let cached;try{cached=localStorage.getItem('workbench-ui-language')||localStorage.getItem('workbench-guest-language');}catch{}
  const choice=(entry==='en'||entry==='zh-CN')?entry:cached||(navigator.language.startsWith('en')?'en':'zh-CN');
  locale=choice==='en'?'en':'zh-CN';
 }catch{}
 document.documentElement.lang=locale;
})();
