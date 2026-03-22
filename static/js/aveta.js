(async function scrollAndExtract() {
  // Fungsi scroll otomatis
  async function scrollWindow(times = 100, delay = 1000, step = 1000) {
    for (let i = 0; i < times; i++) {
      window.scrollBy({ top: step, behavior: 'smooth' });
      console.log(`Scroll ke-${i + 1}`);
      await new Promise(resolve => setTimeout(resolve, delay));
    }
    console.log('Scrolling selesai.');
  }
  // Fungsi konversi relative time → datetime
  function parseRelativeTime(text) {
    const now = new Date();
    if (!text) return null;
    const match = text.match(/(\d+)\s+(second|minute|hour|day|week|month|year)/i);
    if (!match) return text; // fallback kalau format beda (misalnya "kemarin" / "yesterday")
    const value = parseInt(match[1], 10);
    const unit = match[2].toLowerCase();
    let diffMs = 0;
    switch (unit) {
      case "second": diffMs = value * 1000; break;
      case "minute": diffMs = value * 60 * 1000; break;
      case "hour": diffMs = value * 60 * 60 * 1000; break;
      case "day": diffMs = value * 24 * 60 * 60 * 1000; break;
      case "week": diffMs = value * 7 * 24 * 60 * 60 * 1000; break;
      case "month": diffMs = value * 30 * 24 * 60 * 60 * 1000; break;
      case "year": diffMs = value * 365 * 24 * 60 * 60 * 1000; break;
    }
    const reviewDate = new Date(now - diffMs);
    return reviewDate.toISOString().replace("T", " ").split(".")[0]; 
  }
  // Scroll dulu biar semua review muncul
  await scrollWindow(100, 1000, 1000);  
  // Setelah scroll → ekstrak data
  const results = [];
  const containers = document.querySelectorAll('.Svr5cf.bKhjM');
  containers.forEach(container => {
    const data = {};
    // Nama reviewer
    const reviewer = container.querySelector('.X5PpBb');
    data.reviewer_name = reviewer ? reviewer.innerText.trim() : null;
    // Waktu review (raw + real datetime)
    const reviewTime = container.querySelector('.rsqaWe');
    if (reviewTime) {
      data.review_time_raw = reviewTime.innerText.trim();
      data.review_time = parseRelativeTime(data.review_time_raw);
    } else {
      data.review_time_raw = null;
      data.review_time = null;
    }
    // Teks review
    const reviewText = container.querySelector('span[jsname="bN97Pc"]');
    data.review_text = reviewText ? reviewText.innerText.trim() : null;
    // Rating
    const rating = container.querySelector('.GDWaad');
    data.rating = rating ? rating.innerText.trim() : null;
    results.push(data);
  });
  // Simpan ke JSON & download
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
