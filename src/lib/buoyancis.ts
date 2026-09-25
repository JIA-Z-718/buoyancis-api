// 定义后端返回的数据结构类型
export interface VerificationLog {
  date: string;
  raw_amount: number;
  eligible_amount: number;
  delta_days: number;
  weight: number;
  pv_contribution: number;
}

export interface VerificationResponse {
  verification_id: string;
  status: 'PASS' | 'FAIL';
  rent: number;
  required_threshold: number;
  pv_discounted_inflows: number;
  issued_at: string;
  expires_at: string;
  logs: VerificationLog[];
  security_metadata: {
    engine_version: string;
    anti_gaming_baseline: string;
    disclaimer: string;
  };
}

// 专门调用 Python 后端的函数
export async function verifyBuoyancisProof(rent: number): Promise<VerificationResponse> {
  // 发送 POST 请求到我们刚刚测试成功的本地 5001 端口
  const response = await fetch('http://127.0.0.1:5001/api/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rent }),
  });

  if (!response.ok) {
    throw new Error('网络请求失败，请检查后端 app.py 是否在运行');
  }

  return response.json();
}