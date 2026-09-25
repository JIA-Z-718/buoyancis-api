'use client';

import React, { useState } from 'react';
// 引入刚刚第一步写好的 verifyBuoyancisProof 函数
import { verifyBuoyancisProof, VerificationResponse } from '@/lib/buoyancis';

export default function VerificationCard() {
  const [rentInput, setRentInput] = useState<number>(1200);
  const [loading, setLoading] = useState<boolean>(false);
  const [result, setResult] = useState<VerificationResponse | null>(null);

  const handleVerify = async () => {
    setLoading(true);
    try {
      // 点击按钮时，调用 API 请求
      const data = await verifyBuoyancisProof(rentInput);
      setResult(data);
    } catch (err) {
      console.error(err);
      alert('无法连接到后端，请确保运行了 python3 app.py');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: '650px', margin: '20px auto', padding: '24px', backgroundColor: '#0f172a', color: '#f8fafc', borderRadius: '16px', fontFamily: 'sans-serif' }}>
      
      {/* 头部标题区 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #334155', paddingBottom: '16px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '20px', color: '#fff' }}>🛡️ Buoyancis Trust Proof</h2>
          <span style={{ fontSize: '12px', color: '#94a3b8' }}>Engine Version: v0.2.0-heuristic</span>
        </div>
        {result && (
          <span style={{
            padding: '4px 12px',
            borderRadius: '20px',
            fontSize: '12px',
            fontWeight: 'bold',
            backgroundColor: result.status === 'PASS' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(244, 63, 94, 0.2)',
            color: result.status === 'PASS' ? '#34d399' : '#fb7185',
            border: `1px solid ${result.status === 'PASS' ? '#059669' : '#e11d48'}`
          }}>
            {result.status}
          </span>
        )}
      </div>

      {/* 输入框与按钮 */}
      <div style={{ margin: '20px 0', display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
        <div style={{ flex: 1 }}>
          <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '8px' }}>
            Target Monthly Rent (SEK / USD)
          </label>
          <input
            type="number"
            value={rentInput}
            onChange={(e) => setRentInput(Number(e.target.value))}
            style={{
              width: '100%',
              backgroundColor: '#020617',
              border: '1px solid #334155',
              borderRadius: '8px',
              padding: '10px 14px',
              color: '#fff',
              outline: 'none',
              boxSizing: 'border-box'
            }}
          />
        </div>
        <button
          onClick={handleVerify}
          disabled={loading}
          style={{
            backgroundColor: '#10b981',
            color: '#020617',
            border: 'none',
            borderRadius: '8px',
            padding: '10px 20px',
            fontWeight: 'bold',
            cursor: 'pointer',
            opacity: loading ? 0.6 : 1
          }}
        >
          {loading ? 'Calculating...' : 'Verify Inflows'}
        </button>
      </div>

      {/* 计算结果与日志 */}
      {result && (
        <div>
          {/* 总积分与门槛卡片 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', backgroundColor: '#020617', padding: '16px', borderRadius: '12px', marginBottom: '20px' }}>
            <div>
              <div style={{ fontSize: '12px', color: '#64748b' }}>Discounted Present Value (PV)</div>
              <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#34d399' }}>
                ${result.pv_discounted_inflows.toLocaleString()}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '12px', color: '#64748b' }}>Required Threshold (3x Rent)</div>
              <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#e2e8f0' }}>
                ${result.required_threshold.toLocaleString()}
              </div>
            </div>
          </div>

          {/* 交易拆解表格 */}
          <div style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '8px', fontWeight: 'bold' }}>
            90-DAY WEIGHTED BREAKDOWN
          </div>
          <div style={{ overflowX: 'auto', border: '1px solid #334155', borderRadius: '8px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '12px' }}>
              <thead>
                <tr style={{ backgroundColor: '#020617', color: '#64748b', borderBottom: '1px solid #334155' }}>
                  <th style={{ padding: '10px' }}>Date</th>
                  <th style={{ padding: '10px' }}>Raw Amount</th>
                  <th style={{ padding: '10px' }}>Rule B Cap</th>
                  <th style={{ padding: '10px' }}>Weight</th>
                  <th style={{ padding: '10px', textAlign: 'right' }}>PV Contribution</th>
                </tr>
              </thead>
              <tbody>
                {result.logs.map((log, idx) => (
                  <tr key={idx} style={{ borderBottom: '1px solid #1e293b' }}>
                    <td style={{ padding: '10px', fontFamily: 'monospace' }}>{log.date}</td>
                    <td style={{ padding: '10px' }}>${log.raw_amount.toLocaleString()}</td>
                    <td style={{ padding: '10px', color: '#fbbf24', fontFamily: 'monospace' }}>
                      {log.raw_amount !== log.eligible_amount ? `$${log.eligible_amount.toLocaleString()}` : '—'}
                    </td>
                    <td style={{ padding: '10px', fontFamily: 'monospace', color: '#94a3b8' }}>{log.weight}</td>
                    <td style={{ padding: '10px', textAlign: 'right', fontFamily: 'monospace', color: '#34d399', fontWeight: 'bold' }}>
                      +${log.pv_contribution.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 底部验证证明凭证编号 */}
          <div style={{ marginTop: '16px', paddingTop: '12px', borderTop: '1px solid #334155', display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#64748b' }}>
            <span>🔒 Proof ID: {result.verification_id}</span>
            <span>Expires: {new Date(result.expires_at).toLocaleDateString()}</span>
          </div>
        </div>
      )}
    </div>
  );
}