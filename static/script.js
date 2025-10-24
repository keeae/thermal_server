const img = document.getElementById('thermalImg');
const minEl = document.getElementById('min');
const maxEl = document.getElementById('max');
const avgEl = document.getElementById('avg');
const logbox = document.getElementById('logbox');
const cbMax = document.getElementById('cb-max');
const cbMid = document.getElementById('cb-mid');
const cbMin = document.getElementById('cb-min');

let interval = 1000;
let timerImg = null;
let timerStatus = null;

function log(msg){
  const t = new Date().toLocaleTimeString();
  logbox.innerHTML = `<div>[${t}] ${msg}</div>` + logbox.innerHTML;
}

async function updateImage(){
  img.src = '/image?ts=' + Date.now();
}

async function updateStatus(){
  try{
    const r = await fetch('/status');
    const j = await r.json();
    if (j.min !== undefined) {
      minEl.innerText = j.min.toFixed(2);
      maxEl.innerText = j.max.toFixed(2);
      avgEl.innerText = j.avg.toFixed(2);
      cbMax.innerText = j.max.toFixed(1);
      cbMid.innerText = ((j.max+j.min)/2).toFixed(1);
      cbMin.innerText = j.min.toFixed(1);
      log('Status updated');
    } else {
      log('No data yet');
    }
  } catch(e){
    log('Error fetching status: ' + e.message);
  }
}

document.getElementById('refreshInterval').addEventListener('change', (e)=>{
  interval = parseInt(e.target.value);
  restartTimers();
});

function restartTimers(){
  if(timerImg) clearInterval(timerImg);
  if(timerStatus) clearInterval(timerStatus);
  timerImg = setInterval(updateImage, interval);
  timerStatus = setInterval(updateStatus, interval);
}

document.getElementById('btnSave').addEventListener('click', ()=>{
  fetch('/image').then(r=>r.blob()).then(b=>{
    const url = URL.createObjectURL(b);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'thermal_'+Date.now()+'.jpg';
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  });
});

document.getElementById('btnFullscreen').addEventListener('click', ()=>{
  if(!document.fullscreenElement) document.documentElement.requestFullscreen();
  else document.exitFullscreen();
});

window.addEventListener('load', ()=>{
  restartTimers();
  updateStatus();
  log('UI ready');
});
