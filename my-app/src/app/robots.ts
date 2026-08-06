import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        disallow: "/api/",
        allow: "/home",
        crawlDelay: 10,
      },
    ],
    sitemap: ["https://www.example.com/sitemap.xml"],
  };
}
