import type { Row } from "./specs";

/** 一个设定元素的一条版本链：versions 按 next 顺序排，头（最初）在前、尾（当前版）在最后。 */
export interface Chain {
  versions: Row[];
}

const str = (value: unknown) => (value == null ? "" : String(value));

/**
 * 把一屏的版本行按 next 串成一条条链。
 *
 * 会随剧情演变的五类（人物 / 世界规则 / 势力 / 物品 / 关系）每变一次新建一行，旧行的 next
 * 指向新行，next 为空的那行是当前版（见 novel.prisma 的版本链注释）。链头就是**没被任何行
 * next 指向**的那行；从链头顺 next 走到头即得这条链。
 *
 * 两条兜底：next 指向的行不在本次结果里（已被删）→ 当作链尾停下；正常链头收不进去的残行
 * （数据成了环、或没有头）→ 各自成一条单版链，别把它们从界面上弄丢。
 */
export function buildChains(rows: Row[]): Chain[] {
  const byId = new Map<string, number>(); // 行 id → 下标
  rows.forEach((row, i) => {
    const id = str(row.id);
    if (id) byId.set(id, i);
  });

  const pointed = new Set<string>(); // 被别人的 next 指到过的 id
  for (const row of rows) {
    const next = str(row.next);
    if (next) pointed.add(next);
  }

  const used = rows.map(() => false);
  const chains: Chain[] = [];

  const walk = (start: number) => {
    const versions: Row[] = [];
    let i: number | undefined = start;
    while (i !== undefined && !used[i]) {
      used[i] = true;
      const row = rows[i];
      versions.push(row);
      const next = str(row.next);
      i = next ? byId.get(next) : undefined;
    }
    chains.push({ versions });
  };

  rows.forEach((row, i) => {
    if (!pointed.has(str(row.id))) walk(i);
  });
  rows.forEach((_, i) => {
    if (!used[i]) walk(i);
  });

  return chains;
}