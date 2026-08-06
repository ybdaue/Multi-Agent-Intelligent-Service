import { PrismaClient } from '@/generated/prisma/client'
import { PrismaPg } from '@prisma/adapter-pg'
const pool = new PrismaPg({ connectionString: process.env.DATABASE_URL })	//创建连接池
const prisma = new PrismaClient({ adapter: pool })	//创建客户端
export default prisma