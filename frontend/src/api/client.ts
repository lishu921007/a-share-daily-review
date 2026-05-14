import type { Review, LimitupReview, StrongTrendReview } from '../types/review';
async function request<T>(url:string, options?:RequestInit): Promise<T>{
 const res=await fetch(url,{headers:{'Content-Type':'application/json'},...options});
 if(!res.ok){let msg=`HTTP ${res.status}`; try{const j=await res.json(); msg=j.detail||msg}catch{} throw new Error(msg)}
 return res.json();
}
export const api={
 health:()=>request('/api/health'),
 latest:()=>request<{trade_date:string}>('/api/trade/latest'),
 update:(trade_date:string, force=false)=>request<Review>('/api/review/update',{method:'POST',body:JSON.stringify({trade_date,force})}),
 daily:(trade_date:string)=>request<Review>(`/api/review/daily?trade_date=${trade_date}`),
 universe:()=>request<any>('/api/universe/info'),
 list:()=>request<any>('/api/review/list?limit=60'),
 limitup:(end:string, days=60, force=false)=>request<LimitupReview>(`/api/limitup/review?end=${end}&days=${days}&force=${force}`),
 strongTrend:(end:string, top=100, force=false)=>request<StrongTrendReview>(`/api/trend/strong?end=${end}&top=${top}&force=${force}`),
};
