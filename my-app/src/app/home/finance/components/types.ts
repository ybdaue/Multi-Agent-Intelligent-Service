export interface StockData {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  volume: number;
  amount: number;
}

export interface TickPoint {
  time: string;
  price: number;
  volume: number;
  avg_price?: number;
}

export interface KlineResponseData {
  timestamp: number[];
  open: number[];
  high: number[];
  low: number[];
  close: number[];
  volume: number[];
  amount: number[];
}

export interface KlineResponse {
  data: KlineResponseData;
}

export interface SubChart {
  id: string;
  type: string;
}

export interface StockDetail extends StockData {
  intraday: number[];
  open: number;
  high: number;
  low: number;
  prevClose: number;
  turnoverRate: number;
  peRatio: number;
}

export interface StockQuote {
  open: number;
  high: number;
  low: number;
  prevClose: number;
  turnoverRate: number;
}

export interface TickflowStockData {
  symbol: string;
  region: string;
  last_price: number;
  prev_close: number;
  open: number;
  high: number;
  low: number;
  volume: number;
  amount: number;
  timestamp: number;
  ext: {
    type: string;
    name: string;
    change_pct: number;
    change_amount: number;
    amplitude: number;
    turnover_rate: number;
  };
}

export interface TickflowQuoteResponse {
  data: TickflowStockData[];
}
