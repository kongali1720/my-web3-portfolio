"""
KA1720 Arbitrage Bot - BSC Multi-DEX Price Monitor & Auto Trade
=============================================================
Bot yang memantau harga token di beberapa DEX sekaligus,
menghitung selisih harga, dan mengeksekusi arbitrase otomatis
ketika profit melebihi threshold.

PRINSIP ARBITRASE:
  Beli di DEX A (harga murah) -> Jual di DEX B (harga mahal) -> Profit selisih

CONTOH:
  PancakeSwap: 1 BNB = 315 USDT
  Biswap     : 1 BNB = 318 USDT
  Selisih     : 3 USDT per BNB
  Profit      : ~0.95% setelah fee

LEGAL & AMAN:
  - Arbitrase = memanfaatkan perbedaan harga pasar
  - 100% legal di semua negara
  - Tidak melibatkan manipulasi harga
  - Justru membantu market jadi efisien

PREREQUISITE:
  pip install web3 requests python-dotenv pysocks

CARA KERJA:
  1. Scan harga BNB/USDT di PancakeSwap, Biswap, Uniswap V3
  2. Hitung selisih harga antar DEX
  3. Kalau selisih > min_profit_threshold + gas fee -> EKSEKUSI
  4. Buy di DEX murah -> Sell di DEX mahal
  5. Catat semua transaksi ke log
"""

import json
import os
import sys
import time
import math
from datetime import datetime
from web3 import Web3
from dotenv import load_dotenv

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
MIN_PROFIT_THRESHOLD = float(os.getenv("MIN_PROFIT_THRESHOLD", "0.5"))  # Min profit 0.5%
TRADE_AMOUNT_BNB = float(os.getenv("TRADE_AMOUNT_BNB", "0.1"))          # Jumlah BNB per trade
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))                     # Cek setiap 5 detik
LOG_FILE = os.getenv("LOG_FILE", "arb_log.txt")

if not PRIVATE_KEY:
    print("[ERROR] PRIVATE_KEY diperlukan untuk mode auto-trade")
    print("[INFO] Untuk mode monitor saja, ini tidak wajib")

# ============================================================
# DEX CONFIGURATION (BSC)
# ============================================================

DEX_ROUTERS = {
    "PancakeSwap V2": {
        "router": Web3.to_checksum_address("0x10ED43C718714eb63d5aA57B78B54704E256024E"),
        "factory": Web3.to_checksum_address("0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"),
        "version": "V2",
    },
    "SushiSwap": {
        "router": Web3.to_checksum_address("0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506"),
        "factory": Web3.to_checksum_address("0xc35DADB65012eC5796536bD9864eD8773aBc74C4"),
        "version": "V2",
    },
    "BabySwap": {
        "router": Web3.to_checksum_address("0xA527a61703D82139F8a06Bc30097cC9CAA2df5A6"),
        "factory": Web3.to_checksum_address("0x86407bAa071c831E3C9AD76fAa0E2c6aE1e2E71e"),
        "version": "V2",
    },

}

# Token addresses di BSC
TOKENS = {
    "WBNB": Web3.to_checksum_address("0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"),
    "USDT": Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955"),
    "BUSD": Web3.to_checksum_address("0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56"),
    "CAKE": Web3.to_checksum_address("0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82"),
}

# ABI Router untuk getAmountsOut (V2 - kompatibel dengan kebanyakan DEX)
ROUTER_ABI = json.loads('[\
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"},\
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactTokensForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},\
    {"inputs":[{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"},\
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapTokensForExactTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},\
    {"inputs":[],"name":"WETH","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}\
]')

# RPC URLs
RPC_URLS = [
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc-dataseed2.defibit.io",
    "https://bsc-dataseed3.defibit.io",
    "https://bsc-dataseed4.defibit.io",
]

# ============================================================
# CORE: CONNECT TO BSC
# ============================================================

def connect_to_bsc():
    """Connect ke BSC dengan fallback multi-RPC."""
    for rpc in RPC_URLS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={'timeout': 15}))
            if w3.is_connected():
                gas_gwei = w3.from_wei(w3.eth.gas_price, 'gwei')
                print(f"[OK] Terhubung ke BSC | Block: {w3.eth.block_number} | Gas: {gas_gwei:.2f} Gwei")
                return w3
        except Exception:
            continue
    print("[ERROR] Gagal connect ke BSC")
    sys.exit(1)

# ============================================================
# CORE: GET PRICE FROM DEX
# ============================================================

def get_price_from_dex(w3, dex_name, token_in, token_out, amount_in):
    """
    Ambil harga quote dari DEX tertentu.
    
    Returns:
        tuple: (price, amount_out, router_contract)
    """
    dex = DEX_ROUTERS[dex_name]
    
    try:
        router = w3.eth.contract(
            address=dex['router'],
            abi=ROUTER_ABI
        )
        
        path = [token_in, token_out]
        
        # Cek WETH address router
        try:
            weth = router.functions.WETH().call()
        except Exception:
            weth = TOKENS['WBNB']
        
        # Kalau input BNB, pakai WBNB di path
        if token_in == "BNB" or token_in == weth:
            path[0] = weth
        if token_out == "BNB" or token_out == weth:
            path[1] = weth
        
        # Hitung output amount
        amounts = router.functions.getAmountsOut(amount_in, path).call()
        amount_out = amounts[-1]
        
        return amount_out, router
    
    except Exception as e:
        return None, None

def get_bnb_usdt_price(w3, dex_name, amount_bnb_wei):
    """
    Get harga BNB dalam USDT dari DEX tertentu.
    
    Parameters:
        w3             : Web3 instance
        dex_name       : Nama DEX (PancakeSwap V2, Biswap, dll)
        amount_bnb_wei : Jumlah BNB dalam wei (18 decimals)
    
    Returns:
        float : Harga BNB dalam USDT
    """
    amount_out, _ = get_price_from_dex(
        w3, dex_name, TOKENS['WBNB'], TOKENS['USDT'], amount_bnb_wei
    )
    
    if amount_out:
        # USDT di BSC = 18 decimals
        price = amount_out / (10 ** 18)
        return price
    return None

# ============================================================
# CORE: ARBITRAGE SCANNER
# ============================================================

def scan_arbitrage(w3, pair="BNB/USDT"):
    """
    Scan harga di semua DEX dan cari opportunity arbitrase.
    
    Parameters:
        w3   : Web3 instance
        pair : Trading pair (default: BNB/USDT)
    
    Returns:
        list : Daftar opportunity arbitrase
    """
    amount_in = Web3.to_wei(TRADE_AMOUNT_BNB, 'ether')  # Default 0.1 BNB
    
    print(f"\n[SCAN] Mencari opportunity {pair} di {len(DEX_ROUTERS)} DEX...")
    print(f"[SCAN] Amount: {TRADE_AMOUNT_BNB} BNB")
    
    prices = {}
    opportunities = []
    
    # Step 1: Ambil harga dari semua DEX
    for dex_name in DEX_ROUTERS:
        price = get_bnb_usdt_price(w3, dex_name, amount_in)
        
        if price:
            prices[dex_name] = price
            status = "[OK]"
        else:
            status = "[FAIL]"
        
        print(f"  {status} {dex_name:20s} : 1 BNB = {price:.4f} USDT" if price else f"  {status} {dex_name:20s} : Gagal ambil harga")
    
    if len(prices) < 2:
        print("[WARN] Perlu minimal 2 DEX yang aktif untuk arbitrase!")
        return opportunities
    
    # Step 2: Cari selisih harga antar DEX
    print(f"\n[ANALISIS] Mencari selisih harga...")
    
    dex_list = list(prices.keys())
    
    for i in range(len(dex_list)):
        for j in range(len(dex_list)):
            if i == j:
                continue
            
            buy_dex = dex_list[i]
            sell_dex = dex_list[j]
            buy_price = prices[buy_dex]
            sell_price = prices[sell_dex]
            
            # Hitung profit percentage
            if buy_price > 0:
                spread = ((sell_price - buy_price) / buy_price) * 100
                
                # Estimasi biaya
                # Swap fee (0.25% V2 / 0.1% V3) x 2 = ~0.5%
                swap_fee = 0.5
                # Gas fee estimasi (2 swap transactions)
                gas_cost_usdt = estimate_gas_cost_usdt(w3, buy_price)
                
                net_profit_pct = spread - swap_fee - (gas_cost_usdt / (TRADE_AMOUNT_BNB * buy_price) * 100)
                net_profit_usdt = (TRADE_AMOUNT_BNB * sell_price) - (TRADE_AMOUNT_BNB * buy_price) - gas_cost_usdt
                
                opportunity = {
                    'buy_dex': buy_dex,
                    'sell_dex': sell_dex,
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'spread_pct': spread,
                    'swap_fee_pct': swap_fee,
                    'gas_cost_usdt': gas_cost_usdt,
                    'net_profit_pct': net_profit_pct,
                    'net_profit_usdt': net_profit_usdt,
                    'profitable': net_profit_pct > MIN_PROFIT_THRESHOLD
                }
                
                opportunities.append(opportunity)
    
    # Step 3: Sort by profit
    opportunities.sort(key=lambda x: x['net_profit_pct'], reverse=True)
    
    return opportunities

def estimate_gas_cost_usdt(w3, bnb_price):
    """
    Estimasi biaya gas untuk 2 swap transactions dalam USDT.
    """
    gas_per_swap = 200000   # Gas limit estimasi per swap
    total_gas = gas_per_swap * 2  # 2 swaps (buy + sell)
    
    gas_price = w3.eth.gas_price
    gas_cost_bnb = (total_gas * gas_price) / (10 ** 18)
    gas_cost_usdt = gas_cost_bnb * bnb_price
    
    return gas_cost_usdt

# ============================================================
# DISPLAY: PRINT OPPORTUNITIES
# ============================================================

def print_opportunities(opportunities):
    """Tampilkan daftar opportunity arbitrase."""
    
    profitable = [o for o in opportunities if o['profitable']]
    unprofitable = [o for o in opportunities if not o['profitable']]
    
    print(f"\n{'=' * 70}")
    print(f"  HASIL SCAN ARBITRASE")
    print(f"{'=' * 70}")
    
    if profitable:
        print(f"\n  *** PROFITABLE ({len(profitable)} opportunities) ***\n")
        for i, opp in enumerate(profitable[:5], 1):  # Top 5
            marker = ">>> " if opp['profitable'] else "    "
            print(f"  {marker}[{i}] BUY  {opp['buy_dex']:20s} @ {opp['buy_price']:.4f} USDT/BNB")
            print(f"       SELL {opp['sell_dex']:20s} @ {opp['sell_price']:.4f} USDT/BNB")
            print(f"       Spread    : {opp['spread_pct']:+.4f}%")
            print(f"       Swap Fee  : -{opp['swap_fee_pct']:.2f}%")
            print(f"       Gas Cost  : ~${opp['gas_cost_usdt']:.4f}")
            print(f"       NET PROFIT: {opp['net_profit_pct']:+.4f}% (${opp['net_profit_usdt']:.4f})")
            print()
    else:
        print(f"\n  Belum ada opportunity yang profitable.")
        print(f"  Min threshold: {MIN_PROFIT_THRESHOLD}%")
    
    if unprofitable:
        print(f"\n  --- UNPROFITABLE (Top 3 selisih terbesar) ---\n")
        for i, opp in enumerate(unprofitable[:3], 1):
            print(f"    [{i}] {opp['buy_dex']} ({opp['buy_price']:.4f}) -> {opp['sell_dex']} ({opp['sell_price']:.4f}) | {opp['net_profit_pct']:+.4f}%")
    
    print(f"{'=' * 70}")

# ============================================================
# TRADE: EXECUTE ARBITRAGE
# ============================================================

def execute_arbitrage(w3, opportunity):
    """
    Eksekusi trade arbitrase:
    1. Approve WBNB ke router buy
    2. Swap WBNB -> USDT di buy_dex (murah)
    3. Approve USDT ke router sell
    4. Swap USDT -> WBNB di sell_dex (mahal)
    
    Parameters:
        w3           : Web3 instance
        opportunity  : Dict dari scan_arbitrage()
    
    Returns:
        bool : True jika berhasil
    """
    if not PRIVATE_KEY:
        print("[ERROR] PRIVATE_KEY tidak tersedia! Set di .env untuk mode auto-trade.")
        return False
    
    wallet = w3.eth.account.from_key(PRIVATE_KEY)
    
    print(f"\n[TRADE] Eksekusi Arbitrase:")
    print(f"  BUY  : {opportunity['buy_dex']} @ {opportunity['buy_price']:.4f}")
    print(f"  SELL : {opportunity['sell_dex']} @ {opportunity['sell_price']:.4f}")
    print(f"  Est. Profit: ${opportunity['net_profit_usdt']:.4f}")
    
    # Konfirmasi
    confirm = input("  Konfirmasi trade? (YA/n): ").strip().upper()
    if confirm != 'YA':
        print("  [CANCEL] Trade dibatalkan.")
        return False
    
    try:
        amount_bnb = Web3.to_wei(TRADE_AMOUNT_BNB, 'ether')
        
        # --- TRADE 1: BNB -> USDT di Buy DEX ---
        print(f"\n  [1/2] Swap BNB -> USDT di {opportunity['buy_dex']}...")
        
        buy_dex = DEX_ROUTERS[opportunity['buy_dex']]
        buy_router = w3.eth.contract(address=buy_dex['router'], abi=ROUTER_ABI)
        
        nonce = w3.eth.get_transaction_count(wallet.address)
        deadline = int(time.time()) + 300  # 5 menit
        
        # Minimal output (slippage 0.5%)
        expected_usdt = opportunity['buy_price'] * TRADE_AMOUNT_BNB
        min_usdt = int(expected_usdt * 0.995 * (10 ** 18))
        
        tx1 = buy_router.functions.swapExactETHForTokens(
            min_usdt,
            [TOKENS['WBNB'], TOKENS['USDT']],
            wallet.address,
            deadline
        ).build_transaction({
            'chainId': 56,
            'value': amount_bnb,
            'gas': 250000,
            'gasPrice': w3.eth.gas_price,
            'nonce': nonce,
        })
        
        signed_tx1 = w3.eth.account.sign_transaction(tx1, PRIVATE_KEY)
        tx_hash1 = w3.eth.send_raw_transaction(signed_tx1.raw_transaction)
        
        print(f"  TX1 Hash: {tx_hash1.hex()}")
        print(f"  Menunggu konfirmasi...")
        
        receipt1 = w3.eth.wait_for_transaction_receipt(tx_hash1, timeout=120)
        
        if receipt1['status'] != 1:
            print(f"  [FAIL] Trade 1 gagal!")
            return False
        
        print(f"  [OK] Trade 1 berhasil! Gas: {receipt1['gasUsed']:,}")
        
        # --- TRADE 2: USDT -> BNB di Sell DEX ---
        print(f"\n  [2/2] Swap USDT -> BNB di {opportunity['sell_dex']}...")
        
        sell_dex = DEX_ROUTERS[opportunity['sell_dex']]
        sell_router = w3.eth.contract(address=sell_dex['router'], abi=ROUTER_ABI)
        
        # Approve USDT ke sell router
        # (Dalam produksi, approve harus dipisahkan)
        nonce = w3.eth.get_transaction_count(wallet.address)
        
        # Cek USDT balance
        usdt_contract = w3.eth.contract(
            address=TOKENS['USDT'],
            abi=json.loads('[{"inputs":[{"type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"}]')
        )
        usdt_balance = usdt_contract.functions.balanceOf(wallet.address).call()
        print(f"  USDT Balance: {usdt_balance / (10**18):.4f} USDT")
        
        min_bnb = int(amount_bnb * 0.995)  # 0.5% slippage
        
        tx2 = sell_router.functions.swapExactTokensForTokens(
            usdt_balance,
            min_bnb,
            [TOKENS['USDT'], TOKENS['WBNB']],
            wallet.address,
            deadline
        ).build_transaction({
            'chainId': 56,
            'gas': 250000,
            'gasPrice': w3.eth.gas_price,
            'nonce': nonce,
        })
        
        signed_tx2 = w3.eth.account.sign_transaction(tx2, PRIVATE_KEY)
        tx_hash2 = w3.eth.send_raw_transaction(signed_tx2.raw_transaction)
        
        print(f"  TX2 Hash: {tx_hash2.hex()}")
        print(f"  Menunggu konfirmasi...")
        
        receipt2 = w3.eth.wait_for_transaction_receipt(tx_hash2, timeout=120)
        
        if receipt2['status'] != 1:
            print(f"  [FAIL] Trade 2 gagal!")
            return False
        
        print(f"  [OK] Trade 2 berhasil! Gas: {receipt2['gasUsed']:,}")
        
        # --- SUMMARY ---
        bnb_balance_after = w3.eth.get_balance(wallet.address)
        bnb_after = w3.from_wei(bnb_balance_after, 'ether')
        bnb_spent = float(TRADE_AMOUNT_BNB) + (float(receipt1['gasUsed'] * receipt1['effectiveGasPrice']) / 10**18) + (float(receipt2['gasUsed'] * receipt2['effectiveGasPrice']) / 10**18)
        actual_profit = float(bnb_after) - (float(w3.from_wei(bnb_balance_after + Web3.to_wei(bnb_spent, 'ether'), 'ether')))
        
        print(f"\n  {'=' * 40}")
        print(f"  ARBITRASE SELESAI!")
        print(f"  TX1: https://bscscan.com/tx/{tx_hash1.hex()}")
        print(f"  TX2: https://bscscan.com/tx/{tx_hash2.hex()}")
        print(f"  {'=' * 40}")
        
        # Log ke file
        log_trade(opportunity, tx_hash1.hex(), tx_hash2.hex())
        
        return True
        
    except Exception as e:
        print(f"\n  [ERROR] Trade gagal: {e}")
        return False

# ============================================================
# LOKA1720NG
# ============================================================

def log_trade(opportunity, tx_hash1, tx_hash2):
    """Catat trade ke file log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = (
        f"[{timestamp}] "
        f"BUY={opportunity['buy_dex']}@{opportunity['buy_price']:.4f} "
        f"SELL={opportunity['sell_dex']}@{opportunity['sell_price']:.4f} "
        f"PROFIT=${opportunity['net_profit_usdt']:.4f} ({opportunity['net_profit_pct']:+.4f}%) "
        f"TX1={tx_hash1[:16]}... TX2={tx_hash2[:16]}...\n"
    )
    
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(log_line)
        print(f"  [LOG] Trade dicatat ke {LOG_FILE}")
    except Exception:
        pass

# ============================================================
# CONTINUOUS MONITOR MODE
# ============================================================

def continuous_monitor(w3, auto_trade=False):
    """
    Mode monitoring kontinu.
    
    Parameters:
        w3         : Web3 instance
        auto_trade : True untuk otomatis eksekusi trade
    """
    mode = "AUTO-TRADE" if auto_trade else "MONITOR ONLY"
    print(f"\n{'=' * 60}")
    print(f"  MODE: {mode}")
    print(f"  Min Profit: {MIN_PROFIT_THRESHOLD}%")
    print(f"  Amount: {TRADE_AMOUNT_BNB} BNB")
    print(f"  Polling: setiap {POLL_INTERVAL} detik")
    print(f"  Press Ctrl+C untuk berhenti")
    print(f"{'=' * 60}")
    
    scan_count = 0
    
    try:
        while True:
            scan_count += 1
            now = datetime.now().strftime("%H:%M:%S")
            
            print(f"\n--- Scan #{scan_count} @ {now} ---")
            
            opportunities = scan_arbitrage(w3)
            profitable = [o for o in opportunities if o['profitable']]
            
            if profitable:
                best = profitable[0]
                print(f"\n[ALERT] Opportunity ditemukan!")
                print(f"  BUY  {best['buy_dex']} -> SELL {best['sell_dex']}")
                print(f"  Net Profit: {best['net_profit_pct']:+.4f}% (${best['net_profit_usdt']:.4f})")
                
                if auto_trade:
                    success = execute_arbitrage(w3, best)
                    if success:
                        print("[OK] Trade berhasil! Lanjut monitoring...")
                        time.sleep(10)  # Jeda setelah trade
                else:
                    print("[INFO] Mode monitor - tidak auto-trade")
            else:
                # Cek best spread yang ada
                if opportunities:
                    best = opportunities[0]
                    print(f"  Best spread: {best['net_profit_pct']:+.4f}% (threshold: {MIN_PROFIT_THRESHOLD}%)")
            
            print(f"  Next scan in {POLL_INTERVAL}s...", end="\r")
            time.sleep(POLL_INTERVAL)
            
    except KeyboardInterrupt:
        print(f"\n\n[STOP] Monitoring dihentikan. Total scan: {scan_count}")

# ============================================================
# INTERACTIVE MENU
# ============================================================

def print_banner():
    print("""
    ╔══════════════════════════════════════════════════╗
    ║       KA1720 ARBITRAGE BOT - BSC Multi-DEX       ║
    ║       Legal Price Difference Trading System      ║
    ╚══════════════════════════════════════════════════╝
    
    Prinsip: Beli murah di DEX A -> Jual mahal di DEX B
    """)

def print_menu():
    print("""
    Pilih mode:
    
    [1] Scan Sekali       - Cek harga sekali, tampilkan opportunity
    [2] Monitor Mode      - Pantau terus (tanpa auto-trade)
    [3] Auto-Trade Mode   - Pantau + eksekusi trade otomatis
    [4] Custom Scan       - Pilih pair & amount custom
    [5] Panduan Arbitrase - Pelajari cara kerja arbitrase
    [0] Keluar
    
    """)

def print_guide():
    """Panduan lengkap arbitrase crypto."""
    print("""
    ============================================================
    PANDUAN ARBITRASE CRYPTO - BSC
    ============================================================
    
    APA ITU ARBITRASE?
    ------------------
    Arbitrase = membeli aset di satu pasar dan menjualnya di 
    pasar lain dengan harga lebih tinggi, untuk mendapatkan 
    profit dari selisih harga.
    
    Contoh:
      PancakeSwap: 1 BNB = 315 USDT
      Biswap     : 1 BNB = 318 USDT
      Selisih     : 3 USDT (0.95%)
      
      -> Beli di PancakeSwap, Jual di Biswap
      -> Profit: 3 USDT - fee - gas
    
    KENAPA HARGA BEDA-BEDA?
    -----------------------
      - Setiap DEX punya liquidity pool sendiri
      - Supply & demand berbeda di setiap DEX
      - Large trade bisa menggeser harga di satu DEX
      - Inefisiensi pasar = kesempatan arbitrase
    
    JENIS ARBITRASE:
    ----------------
      1. Direct Arbitrase
         A -> B (buy di DEX A, sell di DEX B)
         
      2. Triangular Arbitrase
         A -> B -> C -> A
         Contoh: BNB -> USDT -> CAKE -> BNB
         
      3. Cross-Chain Arbitrase
         BSC -> Ethereum -> Polygon
         Butuh bridge + fee yang tinggi
     
    BIAYA YANG HARUS DIHITUNG:
    --------------------------
      1. Swap Fee DEX (biasanya 0.1% - 0.3%)
      2. Gas Fee (BNB) - 2 transaksi
      3. Slippage (perbedaan harga saat eksekusi)
      4. Bridge fee (kalau cross-chain)
      
      NET PROFIT = Spread - Fee - Gas - Slippage
      
      Kalau net profit > 0 -> EXECUTE!
      Kalau net profit <= 0 -> SKIP!
    
    RISIKO:
    -------
      1. Price Change - Harga bisa berubah saat eksekusi
      2. Failed TX - Trade bisa fail jika slippage terlalu besar
      3. MEV Bots - Bot lain bisa front-run trade kamu
      4. Gas Spike - Gas naik tiba-tiba
      5. Liquidity - Pool bisa kering mendadak
      
    MITIGASI RISIKO:
    ----------------
      - Gunakan slippage protection (0.5-1%)
      - Set minimum profit threshold (0.5-1%)
      - Jangan trade dengan jumlah terlalu besar
      - Monitor gas price sebelum trade
      - Gunakan Flashbots (di Ethereum) untuk anti-front-running
      
    TOOLS PROFESIONAL:
    ------------------
      - 1inch API - Aggregator DEX terbaik
      - Paraswap API - Multi-DEX routing
      - Coingecko API - Harga market global
      - DexScreener - Monitor pool DEX
      - Dune Analytics - Analisis on-chain data
      
    TIPS UNTUK PEMULA:
    ------------------
      1. Mulai dengan mode MONITOR dulu (tanpa auto-trade)
      2. Observe pattern harga selama 1-2 hari
      3. Mulai trade dengan jumlah kecil (0.05-0.1 BNB)
      4. Naikkan pelan-pelan setelah paham pola
      5. Catat semua trade ke spreadsheet
      6. Hitung ROI mingguan/bulanan
      
    PROFIT REALISTIS:
    -----------------
      - 0.1-0.5% per trade (setelah fee & gas)
      - 5-20 trades per hari (kalau aktif)
      - $1-10 per trade (modal kecil)
      - $10-100 per trade (modal sedang)
      - $100-1000 per trade (modal besar)
      
      Annual return: 20-100% (tergantung market condition)
    
    ============================================================
    """)

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print_banner()
    
    # Connect ke BSC
    w3 = connect_to_bsc()
    
    if PRIVATE_KEY:
        try:
            wallet = w3.eth.account.from_key(PRIVATE_KEY)
            bnb_bal = w3.from_wei(w3.eth.get_balance(wallet.address), 'ether')
            print(f"[INFO] Wallet: {wallet.address}")
            print(f"[INFO] BNB Balance: {bnb_bal:.4f} BNB")
        except Exception:
            print("[WARN] PRIVATE_KEY tidak valid, mode auto-trade tidak tersedia")
    
    while True:
        print_menu()
        choice = input("Pilih [0-5]: ").strip()
        
        if choice == '0':
            print("Keluar. Happy trading!")
            break
        
        elif choice == '1':
            opportunities = scan_arbitrage(w3)
            print_opportunities(opportunities)
        
        elif choice == '2':
            continuous_monitor(w3, auto_trade=False)
        
        elif choice == '3':
            if not PRIVATE_KEY:
                print("[ERROR] Set PRIVATE_KEY di .env untuk auto-trade!")
                continue
            continuous_monitor(w3, auto_trade=True)
        
        elif choice == '4':
            print("\n[INFO] Pair yang tersedia: BNB/USDT, BNB/BUSD, BNB/CAKE")
            pair = input("Masukkan pair (default: BNB/USDT): ").strip() or "BNB/USDT"
            amount = float(input(f"Masukkan jumlah BNB (default: {TRADE_AMOUNT_BNB}): ").strip() or TRADE_AMOUNT_BNB)
            
            # Temporarily override
            TRADE_AMOUNT_BNB = amount
            
            opportunities = scan_arbitrage(w3)
            print_opportunities(opportunities)
            TRADE_AMOUNT_BNB = float(os.getenv("TRADE_AMOUNT_BNB", "0.1"))  # Reset
        
        elif choice == '5':
            print_guide()
        
        else:
            print("[ERROR] Pilihan tidak valid!")
