function getDocumentDownloadFilename(fileName, fallbackId = null) {
  const fallback = fallbackId == null ? 'document.pdf' : `document-${fallbackId}.pdf`;
  const cleaned = String(fileName || '')
    .replace(/[\\/:*?"<>|\x00-\x1f]/g, '-')
    .replace(/\s+/g, ' ')
    .trim();
  if (!cleaned) return fallback;
  return cleaned.toLowerCase().endsWith('.pdf') ? cleaned : `${cleaned}.pdf`;
}

function canPickDownloadDirectory(win) {
  return Boolean(win && typeof win.showDirectoryPicker === 'function');
}

async function saveBlobToPickedDirectory(win, blob, fileName) {
  const directoryHandle = await pickDownloadDirectory(win);
  await writeBlobToDirectory(directoryHandle, blob, fileName);
}

async function pickDownloadDirectory(win) {
  if (!canPickDownloadDirectory(win)) {
    throw new Error('Folder selection is not supported by this browser.');
  }
  return win.showDirectoryPicker({ mode: 'readwrite' });
}

async function writeBlobToDirectory(directoryHandle, blob, fileName) {
  const fileHandle = await directoryHandle.getFileHandle(fileName, { create: true });
  const writable = await fileHandle.createWritable();
  try {
    await writable.write(blob);
  } finally {
    await writable.close();
  }
}

module.exports = {
  canPickDownloadDirectory,
  getDocumentDownloadFilename,
  pickDownloadDirectory,
  saveBlobToPickedDirectory,
  writeBlobToDirectory,
};
