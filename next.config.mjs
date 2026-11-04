/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pages are generated at build time from data/*.json; every daily data commit triggers a Vercel rebuild.
  reactStrictMode: true,
  outputFileTracingIncludes: { "/*": ["./data/**/*"] },
};
export default nextConfig;
