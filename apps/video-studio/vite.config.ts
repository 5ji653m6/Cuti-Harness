import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

// https://vitejs.dev/config/
export default defineConfig(({ mode, command }) => {
  // 加载所有环境变量（包括 .env.local）
  const env = loadEnv(mode, process.cwd(), '');

  console.log('🔧 Vite Config - Mode:', mode);
  console.log('🔧 Vite Config - Command:', command);
  console.log('🔧 Vite Config - VITE_BACKEND_URL:', env.VITE_BACKEND_URL);
  console.log('🔧 Vite Config - VITE_CUTI_BACKEND_URL:', env.VITE_CUTI_BACKEND_URL);

  // ✅ 统一配置部署路径 - 与后端路由对齐
  // 开发环境：使用 / (方便本地访问 http://localhost:5173/)
  // Open-source self-host defaults to /. Deployments may still mount below a prefix.
  const base = env.VITE_BASE_PATH || '/';
  console.log('🔧 Vite Config - Base path:', base);
  console.log("env.VITE_BACKEND_URL", env.VITE_BACKEND_URL);

  const httpTarget = (...candidates: Array<string | undefined>) => {
    for (const raw of candidates) {
      const value = (raw || "").trim();
      if (/^https?:\/\//i.test(value)) return value;
    }
    return undefined;
  };
  // Video Runtime is 8001 in compose. Empty proxy target crashes http-proxy
  // (`Cannot read properties of null (reading 'split')`) and Vite shows the overlay.
  const runtimeTarget = httpTarget(
    env.VITE_VIDEO_RUNTIME_URL,
    env.VITE_VIDEOCHAT_URL,
    "http://127.0.0.1:8001",
  ) ?? "http://127.0.0.1:8001";
  const apiTarget = httpTarget(env.VITE_CUTI_BACKEND_URL, env.VITE_BACKEND_URL, runtimeTarget)
    ?? runtimeTarget;
  // Local Vite proxies /api/cv-v1 onto the Runtime /api/cuti mount.

  // 分享链接：标题、简介、缩略图（Open Graph / Twitter Card）
  const siteUrl = env.VITE_SITE_URL || (env.VITE_BACKEND_URL ? new URL(env.VITE_BACKEND_URL).origin : '');
  const ogImageUrl = siteUrl ? `${siteUrl.replace(/\/$/, '')}${base.replace(/\/$/, '')}/logo-internal.png` : '';
  const ogTitle = env.VITE_OG_TITLE || 'Cuti - AI 创作搭子';
  const ogDescription = env.VITE_OG_DESCRIPTION || '用 AI 创造视频、音乐与图像，你的创作搭子';

  return {
    // ✅ 配置资源基础路径
    base,

    plugins: [
      react(),
      // 注入分享链接 meta 标签（标题、简介、缩略图）
      {
        name: 'html-meta-og',
        transformIndexHtml(html:string) {
          const metaTags = [
            '<meta name="description" content="' + ogDescription.replace(/"/g, '&quot;') + '">',
            '<meta property="og:title" content="' + ogTitle.replace(/"/g, '&quot;') + '">',
            '<meta property="og:description" content="' + ogDescription.replace(/"/g, '&quot;') + '">',
            '<meta property="og:type" content="website">',
            '<meta name="twitter:card" content="summary_large_image">',
            '<meta name="twitter:title" content="' + ogTitle.replace(/"/g, '&quot;') + '">',
            '<meta name="twitter:description" content="' + ogDescription.replace(/"/g, '&quot;') + '">',
          ];
          if (siteUrl) {
            const ogUrl = siteUrl.replace(/\/$/, '') + (base === '/' ? '' : base.replace(/\/$/, ''));
            metaTags.push('<meta property="og:url" content="' + ogUrl.replace(/"/g, '&quot;') + '">');
          }
          if (ogImageUrl) {
            metaTags.push('<meta property="og:image" content="' + ogImageUrl.replace(/"/g, '&quot;') + '">');
            metaTags.push('<meta name="twitter:image" content="' + ogImageUrl.replace(/"/g, '&quot;') + '">');
          }
          return html.replace('</head>', metaTags.join('\n    ') + '\n  </head>');
        },
      },
    ].filter(Boolean),

    build: {
      sourcemap: false,
      minify: 'esbuild',
    },

    server: {
      host: "::",
      // 8080 is reserved by the self-hosted media service.
      port: 5173,
      // 允许通过域名访问
      allowedHosts: [
        'localhost',
        '127.0.0.1',
     ],
      // 配置 HMR（热模块替换）
      // ⚠️ 只在开发模式（npm run dev）启用 HMR
      // ⚠️ 构建模式（npm run build）不需要 HMR
      hmr: command === 'serve' ? true : false,
      proxy: {
        // 兼容旧路径：/api/cuti 仍转发到 VITE_CUTI_BACKEND_URL
        '/api/cuti': {
          target: apiTarget,
          changeOrigin: true,
          secure: false,
          rewrite: (path) => path,
          configure: (proxy) => {
            proxy.on('proxyReq', (_proxyReq, req, _res) => {
              console.log('🔄 Cuti proxy:', req.method, req.url, '→', apiTarget);
            });
          },
        },
        // Studio historical prefix /api/cv-v1 → Runtime /api/cuti
        '/api/cv-v1': {
          target: apiTarget,
          changeOrigin: true,
          secure: false,
          rewrite: (path) => path.replace(/^\/api\/cv-v1/, '/api/cuti'),
          configure: (proxy) => {
            proxy.on('proxyReq', (_proxyReq, req, _res) => {
              console.log('🔄 Cuti proxy:', req.method, req.url, '→', apiTarget);
            });
          },
        },
        // Migrated DeepSeek BFF is mounted by Video Runtime on port 8001.
        // Legacy deployments can still override this with VITE_VIDEOCHAT_URL.
        '/chat-v1': {
          target: runtimeTarget,
          changeOrigin: true,
          secure: false,
        },
        '/api/video': {
          target: runtimeTarget,
          changeOrigin: true,
          secure: false,
        },
        // 未配 VITE_BACKEND_URL 时跟 Runtime，避免 http-proxy target 为 null 把 Vite overlay 打出来
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          secure: false,
          configure: (proxy, _options) => {
            proxy.on('proxyReq', (_proxyReq, req, _res) => {
              console.log('🔄 Proxying:', req.method, req.url, '→', apiTarget);
            });
          },
        },
      },
      // ⚠️ 重要：修复 SPA 路由问题
      // 当访问 /cuti/* 时，返回 index.html
      middlewareMode: false,
      fs: {
        strict: false,
      },
    },
    // ✅ 预览模式配置（构建后）
    preview: {
      port: 5173,
      host: "::",
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
      dedupe: ["react", "react-dom"],
    },
  };
});
