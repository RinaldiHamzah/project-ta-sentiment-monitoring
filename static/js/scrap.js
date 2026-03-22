async function scrollWindow(times = 1000, delay = 1000, step = 1000) {
  for (let i = 0; i < times; i++) {
    window.scrollBy({
      top: step,
      behavior: 'smooth'
    });
    console.log(`Window scroll ke-${i + 1}`);
    await new Promise(resolve => setTimeout(resolve, delay));
  }
  console.log('Scrolling selesai.');
}
scrollWindow();

(function extractAndDownloadData() {
  const results = [];
  const containers = document.querySelectorAll('.Svr5cf.bKhjM');
  containers.forEach(container => {
    const data = {};
    // Ambil teks dari .GDWaad
    const gdwaad = container.querySelector('.GDWaad');
    data.gdwaad_text = gdwaad ? gdwaad.innerText.trim() : null;
    // Cek apakah ada .STQFb.eoY5cb
    const stqfb = container.querySelector('.STQFb.eoY5cb');
    if (stqfb) {
      const k7obsc = stqfb.querySelector('.K7oBsc');
      data.k7obsc_text = k7obsc ? k7obsc.innerText.trim() : null;
    } else {
      data.k7obsc_text = null; // Lewati jika tidak ada
    }
    results.push(data);
  });
  // Konversi ke JSON dan buat file untuk diunduh
  const blob = new Blob([JSON.stringify(results, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'aveta.json';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  console.log('Data berhasil diekstrak dan diunduh sebagai aveta.json');
})();