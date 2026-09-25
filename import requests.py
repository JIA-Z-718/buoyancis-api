import requests
import json
import numpy as np

# 系统配置
CLIENT_ID = "f4b2cc720f3648f9b946cc64d8cabf7a"
CLIENT_SECRET = "62afb843beb243d288140285560fb6f1"
BASE_URL = "https://api.tink.com"

def get_user_token(auth_code):
    url = f"{BASE_URL}/api/v1/oauth/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": auth_code
    }
    response = requests.post(url, data=payload)
    return response.json().get("access_token") if response.status_code == 200 else None

def calculate_trust_rank(nodes, matrix):
    """计算特征向量中心度：量化每个节点在信用映射图中的权重"""
    n = len(matrix)
    # 轉置矩陣並添加小擾動项以確保計算穩定性
    adj_matrix = matrix.T + np.eye(n) * 0.01
    eigenvalues, eigenvectors = np.linalg.eig(adj_matrix)
    max_idx = np.argmax(eigenvalues)
    trust_vector = np.absolute(eigenvectors[:, max_idx])
    # 歸一化為 0-100 分
    scores = (trust_vector / np.sum(trust_vector)) * 100
    return sorted(zip(nodes, scores), key=lambda x: x[1], reverse=True)

def fetch_and_analyze(access_token):
    url = f"{BASE_URL}/data/v2/transactions"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        transactions = response.json().get("transactions", [])
        print(f"\n[系統日誌] 成功獲取 {len(transactions)} 筆交易。")
        
        # 1. 建立矩陣
        counterparties = list(set([tx.get("descriptions", {}).get("original", "Unknown") for tx in transactions]))
        nodes = ["YOU"] + counterparties
        node_to_idx = {node: i for i, node in enumerate(nodes)}
        matrix = np.zeros((len(nodes), len(nodes)))
        
        for tx in transactions:
            desc = tx.get("descriptions", {}).get("original", "Unknown")
            amt = tx.get("amount", {}).get("value", {})
            val = float(amt.get("unscaledValue", 0)) / (10 ** int(amt.get("scale", 0)))
            u_idx, v_idx = node_to_idx["YOU"], node_to_idx[desc]
            if val < 0: matrix[u_idx][v_idx] += abs(val)
            else: matrix[v_idx][u_idx] += abs(val)

        # 2. 運行算法
        rankings = calculate_trust_rank(nodes, matrix)
        
        print("\n=== 跨國信任映射：TrustRank 排名 ===")
        print(f"{'節點名稱':<35} | {'信任分 (pts)':<15}")
        print("-" * 55)
        for name, score in rankings:
            print(f"{name:<35} | {score:>12.2f}")
        print("\n[系統日誌] 映射完成。高分節點代表你信用網絡中的核心影響力來源。")
    else:
        print(f"[錯誤] 數據讀取失敗: {response.text}")

if __name__ == "__main__":
    print(">>> 啟動跨國信任映射系統 (MVP v1.0) <<<")
    # 請在此處填入新鲜截獲的 code
    new_code = "90028462c9904228b105bcae08608315" 
    
    token = get_user_token(new_code)
    if token:
        fetch_and_analyze(token)
    else:
        print("[提示] Auth Code 已過期，請去瀏覽器刷新 Tink Link 獲取新 Code。")