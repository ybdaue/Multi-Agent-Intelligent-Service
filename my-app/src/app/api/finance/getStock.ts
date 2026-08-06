"use server"

import { requestJSON } from "@/lib/fetch";
import { env } from "@/lib/env";

export async function getNowSingleStock<T>(symbol: string) {
  return await requestJSON<T>(`https://api.tickflow.org/v1/quotes?symbols=${symbol}`,{
    method: 'GET',
    headers: {'x-api-key': env.TICKFLOW_KEY},
    cache:"no-cache"
  });
}

export async function getSingleStockKline<T>(
  symbol: string,
  count?: bigint,
  start_time?: number,
  end_time?: number
) {
  const params = new URLSearchParams({ symbol });
  if (count !== undefined) params.append("count", count.toString());
  if (start_time !== undefined) params.append("start_time", start_time.toString());
  if (end_time !== undefined) params.append("end_time", end_time.toString());

  const query = `https://api.tickflow.org/v1/klines?${params.toString()}`;

  return await requestJSON<T>(query, {
    method: "GET",
    headers: { "x-api-key": env.TICKFLOW_KEY },
    cache: "force-cache",
    next:{
      revalidate: 3600
    }
  });
}