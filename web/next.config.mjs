/** @type {import('next').NextConfig} */
// `standalone` output bundles a minimal server + only the used node_modules, so the Docker
// image for the web service stays small (review M-17).
const nextConfig = { reactStrictMode: true, output: "standalone" };
export default nextConfig;
