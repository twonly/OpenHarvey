export async function api(path, {method='GET', body, headers={}, signal, timeout=method==='GET'?30000:120000}={}) {
  const controller=new AbortController();
  const abort=()=>controller.abort(signal.reason);
  if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
  const timer=setTimeout(()=>controller.abort(new DOMException('请求等待超时','TimeoutError')),timeout);
  const options = {method, credentials:'same-origin', headers:{...headers},signal:controller.signal};
  try{
  if (method !== 'GET') options.headers['X-Workbench-Request']='1';
  if (body instanceof File || body instanceof Blob) options.body=body;
  else if (body !== undefined) { options.headers['Content-Type']='application/json'; options.body=JSON.stringify(body); }
  const response=await fetch(path, options);
  if(!response.ok){
    const data=await response.json().catch(()=>({}));
    if(response.status===401) document.dispatchEvent(new Event('session-expired'));
    const error=new Error(typeof data.detail==='string'?data.detail:`请求失败（${response.status}）`);
    if(response.status===403&&/注册/.test(error.message))document.dispatchEvent(new CustomEvent('registration-required',{detail:error.message}));
    error.status=response.status;throw error;
  }
  if(response.status===204) return null;
  if(response.status===202 && !response.headers.get('content-type')?.includes('application/json')) return null;
  const result=await response.json();if(method!=='GET'&&path.startsWith('/api/threads/'))document.dispatchEvent(new Event('usage-changed'));return result;
  }catch(error){
    if(signal?.aborted)throw new DOMException('已切换对话','AbortError');
    if(controller.signal.aborted)throw new Error(method==='GET'?'读取超时，请点击当前对话重试。':'请求超时，结果尚未确认，请先刷新查看是否已保存。');
    if(error instanceof TypeError)throw new Error(method==='GET'?'网络连接中断，请重试。':'网络连接中断，结果尚未确认，请先刷新查看是否已保存。');
    throw error;
  }finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
}

export function upload(path,file){
  return api(path,{method:'POST',body:file,headers:{'X-Filename':encodeURIComponent(file.name)}});
}
