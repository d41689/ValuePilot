const AUTH_PUBLIC_PATHS = ['/login', '/register'];

const isPublicAuthPath = (pathname) => AUTH_PUBLIC_PATHS.includes(pathname);

module.exports = {
  AUTH_PUBLIC_PATHS,
  isPublicAuthPath,
};
