// Local player page: drop a video + .srt/.vtt and get the same subtitle bar,
// card, subtitle browser and mining as on YouTube (via youtube.js).
const SERVER = "http://127.0.0.1:8766";
const $ = id => document.getElementById(id);
let videoFile = null, uploaded = false;

async function openFiles(files) {
  const v = files.find(f => f.type.startsWith("video/") || /\.(mp4|mkv|webm|mov)$/i.test(f.name));
  const s = files.find(f => /\.(srt|vtt)$/i.test(f.name));
  if (!v || !s) return void ($("status").textContent = `Need both a video and a subtitle file (got ${files.map(f => f.name).join(", ")})`);
  $("status").textContent = "Parsing subtitles…";
  videoFile = v;
  uploaded = false;
  const vid = `local:${v.name}:${v.size}`;               // name + size identifies the file for bookmarks/media
  $("video").src = URL.createObjectURL(v);
  $("title").textContent = v.name.replace(/\.[^.]+$/, "");
  document.title = `${$("title").textContent} · Yuja`;
  $("drop").hidden = true;
  $("stage").hidden = false;
  mountPlayer(vid, $("movie_player"));
  startCues(await api("/local/subs", { vid, text: await s.text() }));
}

// Mining needs the video on the server to cut audio + a frame; send it once (disk -> localhost).
window.beforeMine = async media => {
  if (!media?.vid?.startsWith("local:") || uploaded) return;
  notice("Preparing video for mining…");
  const r = await fetch(`${SERVER}/local/media?vid=${encodeURIComponent(media.vid)}`, { method: "POST", body: videoFile });
  hideNotice();
  if (!r.ok) throw new Error("upload failed");
  uploaded = true;
};

const drop = $("drop");
["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", e => openFiles([...e.dataTransfer.files]));
$("pick").addEventListener("change", e => openFiles([...e.target.files]));
wireListeners();
// The video's own fullscreen button would hide Yuja's subtitle bar: fullscreen the whole player instead.
document.addEventListener("fullscreenchange", () => document.fullscreenElement === $("video")
  && document.exitFullscreen().then(() => $("movie_player").requestFullscreen()));
