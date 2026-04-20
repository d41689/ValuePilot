function canUploadDocuments(role) {
  return role === 'admin';
}

function getDocumentsUploadNotice(role) {
  if (canUploadDocuments(role)) {
    return null;
  }

  return 'You are not an admin, so you cannot upload files from this workspace.';
}

module.exports = {
  canUploadDocuments,
  getDocumentsUploadNotice,
};
