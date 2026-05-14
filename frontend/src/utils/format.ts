export const pct=(v:number)=>`${(v*100).toFixed(2)}%`;
export const chg=(v:number)=>`${v>=0?'+':''}${v.toFixed(2)}%`;
export const money=(v:number)=>{const n=Number(v||0); if(Math.abs(n)>=10000)return `${(n/10000).toFixed(2)}亿`; return `${n.toFixed(0)}万`;};
export const today=()=>{const d=new Date(); return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}`};
export const inputDate=(d:string)=> d ? `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}` : '';
export const compact=(d:string)=>d.replaceAll('-','');
