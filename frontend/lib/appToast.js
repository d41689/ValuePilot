const APP_TOAST_TYPES = ['success', 'error', 'warning', 'info'];

function normalizeAppToastType(type) {
  return APP_TOAST_TYPES.includes(type) ? type : 'info';
}

function buildAppToastPayload({ type, title, description }) {
  const appType = normalizeAppToastType(type);
  return {
    appType,
    title,
    description,
    variant: appType === 'error' ? 'destructive' : 'default',
  };
}

function showAppToast(toast, options) {
  return toast(buildAppToastPayload(options));
}

module.exports = {
  APP_TOAST_TYPES,
  normalizeAppToastType,
  buildAppToastPayload,
  showAppToast,
};
