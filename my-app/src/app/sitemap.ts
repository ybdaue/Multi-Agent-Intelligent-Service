import type { MetadataRoute } from "next";
import { requestJSON } from "@/lib/fetch";

export async function generateSitemaps() {
  const total = 150000;
  const chunkSize = total / 50000;
  return Array.from({ length: chunkSize }, (_, i) => {
    return {
      id: i.toString(),
    };
  });
}

export default async function sitemap(props: {
  id: Promise<string>;
}): Promise<MetadataRoute.Sitemap> {
  const id = await props.id;
  const page = Number(id) + 1;
  const pageSize = 100;
  const list = await requestJSON<{ id: number }[]>(
    `https://jsonplaceholder.typicode.com/posts?_page=${page}&_limit=${pageSize}`,
  );
  return list.map((item: { id: number }) => {
    return {
      url: `https://www.example.com/posts/${item.id}`,
      lastModified: new Date().toISOString(),
    };
  });
}
