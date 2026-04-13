// ============================================================
// CONTOH SMART CONTRACT - BELAJAR VULNERABILITY
// ============================================================
// File ini berisi contoh contract VULNERABLE vs FIXED
// untuk pembelajaran smart contract security auditing.
// ============================================================

// ============================
// 1. VULNERABLE: Hidden Mint Backdoor
// ============================
// Token ini punya fungsi mint yang hanya bisa dipanggil owner
// Owner bisa mencetak token tak terbatas kapan saja
// Ini adalah TANDA RUG PULL / SCAM

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract ScamToken_VULNERABLE is ERC20 {
    address public owner;

    constructor(string memory name, string memory symbol) ERC20(name, symbol) {
        owner = msg.sender;
        _mint(msg.sender, 1000000 * 10 ** decimals()); // Initial supply 1 juta
    }

    // ============================
    // VULNERABILITY: Mint Backdoor!
    // ============================
    // Owner bisa cetak token sebanyak yang dia mau
    // Artinya supply tidak terbatas, harga bisa turun drastis
    function mint(address to, uint256 amount) external {
        require(msg.sender == owner, "Only owner");
        _mint(to, amount); // BISA CETAK TAK TERBATAS!
    }

    // Owner bisa transfer dari wallet siapa saja
    function stealFrom(address from, address to, uint256 amount) external {
        require(msg.sender == owner, "Only owner");
        _transfer(from, to, amount); // BISA CURI TOKEN ORANG!
    }
}


// ============================
// 1. FIXED: No Mint After Deployment
// ============================
// Token yang aman - supply FIXED, tidak bisa mint lagi

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract SafeToken_FIXED is ERC20 {
    constructor(string memory name, string memory symbol) ERC20(name, symbol) {
        // Mint HANYA di constructor (saat deployment)
        // Setelah ini, supply TIDAK BISA bertambah
        _mint(msg.sender, 1000000 * 10 ** decimals());
    }

    // TIDAK ADA fungsi mint!
    // TIDAK ADA fungsi stealFrom!
    // Supply = 1 juta, PERMANEN
}


// ============================
// 2. VULNERABLE: Pausable Transfer (Honeypot Pattern)
// ============================
// Owner bisa freeze semua transfer kapan saja
// Holder tidak bisa menjual token mereka

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/security/Pausable.sol";

contract HoneypotToken_VULNERABLE is ERC20, Pausable {
    address public owner;

    constructor(string memory name, string memory symbol) ERC20(name, symbol) {
        owner = msg.sender;
        _mint(msg.sender, 1000000 * 10 ** decimals());
    }

    // ============================
    // VULNERABILITY: Override transfer dengan pause!
    // ============================
    // Owner bisa pause transfer SEWAKTU-WAKTU
    // Ketika paused, TIDAK ADA YANG BISA JUAL
    function _beforeTokenTransfer(address from, address to, uint256 amount) 
        internal override whenNotPaused 
    {
        super._beforeTokenTransfer(from, to, amount);
    }

    // Owner bisa pause kapan saja
    function pause() external {
        require(msg.sender == owner);
        _pause(); // SEMUA TRANSFER DI-FREEZE!
    }

    function unpause() external {
        require(msg.sender == owner);
        _unpause();
    }
}


// ============================
// 3. VULNERABLE: Excessive Fee (Soft Rug)
// ============================
// Token mengambil fee 50% setiap transfer
// Secara teknis bisa transfer, tapi value hilang separuh

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract FeeToken_VULNERABLE is ERC20 {
    address public owner;
    uint256 public feePercent; // dalam basis points (100 = 1%)

    constructor(string memory name, string memory symbol) ERC20(name, symbol) {
        owner = msg.sender;
        feePercent = 5000; // 50% FEE! Setiap transfer, 50% potong!
        _mint(msg.sender, 1000000 * 10 ** decimals());
    }

    // ============================
    // VULNERABILITY: Fee 50% setiap transfer!
    // ============================
    // Transfer 100 token, receiver cuma dapat 50
    // 50 token lagi masuk ke owner
    // Ini "soft rug pull" - token bisa jual tapi value hilang
    function transfer(address to, uint256 amount) public override returns (bool) {
        uint256 fee = (amount * feePercent) / 10000;
        uint256 amountAfterFee = amount - fee;

        super.transfer(owner, fee);        // 50% ke owner
        super.transfer(to, amountAfterFee); // 50% ke receiver
        return true;
    }

    // Owner bisa ubah fee kapan saja, bahkan jadi 100%
    function setFee(uint256 newFee) external {
        require(msg.sender == owner);
        feePercent = newFee; // Bisa diubah jadi 100%!
    }
}


// ============================
// 4. VULNERABLE: Proxy Pattern (Upgradable Scam)
// ============================
// Contract logic bisa diganti kapan saja oleh owner
// Hari ini aman, besok bisa jadi malicious

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract ProxyScam_VULNERABLE {
    address public implementation;
    address public owner;

    constructor() {
        owner = msg.sender;
    }

    // ============================
    // VULNERABILITY: Owner bisa ganti implementation!
    // ============================
    // Semua call diteruskan ke "implementation" contract
    // Owner bisa ganti implementation ke contract MALICIOUS
    // Semua data/token bisa dicuri
    function upgradeTo(address newImplementation) external {
        require(msg.sender == owner);
        implementation = newImplementation; // GANTI LOGIC KAPAN SAJA!
    }

    // Semua function call diteruskan ke implementation
    fallback() external payable {
        address impl = implementation;
        assembly {
            calldatacopy(0, 0, calldatasize())
            let result := delegatecall(gas(), impl, 0, calldatasize(), 0, 0)
            returndatacopy(0, 0, returndatasize())
            switch result
            case 0 { revert(0, returndatasize()) }
            default { return(0, returndatasize()) }
        }
    }
}


// ============================
// 5. VULNERABILITY: Self-Destruct
// ============================
// Owner bisa menghapus seluruh contract

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract DestructToken_VULNERABLE is ERC20 {
    address public owner;

    constructor(string memory name, string memory symbol) ERC20(name, symbol) {
        owner = msg.sender;
        _mint(msg.sender, 1000000 * 10 ** decimals());
    }

    // ============================
    // VULNERABILITY: Owner bisa HAPUS contract!
    // ============================
    // Semua token hilang, contract mati
    // Semua orang yang hold token = rugi total
    function destroy() external {
        require(msg.sender == owner);
        selfdestruct(payable(owner)); // CONTRACT DIHAPUS!
    }
}


// ============================================================
// CHEAT SHEET: Cara Cek Token Secara Manual
// ============================================================

/*
LANGKAH 1: CEK DI BSCSCAN/ETHERSCAN
-----------------------------------
1. Buka bscscan.com/address/{TOKEN_ADDRESS}
2. Klik tab "Contract" - apakah source code terverifikasi?
3. Scroll ke function list - cari fungsi berbahaya:
   - mint()           → CRITICAL: Bisa cetak token
   - pause()          → HIGH: Bisa freeze transfer
   - blacklist()      → MEDIUM: Bisa blokir address
   - destroy()        → CRITICAL: Bisa hapus contract
   - setFee()         → HIGH: Bisa ubah fee
   - upgradeTo()      → MEDIUM: Proxy pattern
   - transferOwnership() → Cek siapa owner baru

LANGKAH 2: CEK LIQUIDITY
------------------------
1. Buka PancakeSwap atau DexScreener
2. Cari pair token tersebut
3. Cek apakah LP terkunci:
   - Buka pinkswap.finance (PinkLock)
   - Buka unicrypt.network
   - Cari token address
   - Pastikan LP locked minimal 6 bulan
4. Kalau LP tidak locked → RUG PULL RISK TINGGI

LANGKAH 3: CEK TOP HOLDERS
--------------------------
1. Buka bscscan.com/token/{TOKEN_ADDRESS}#balances
2. Lihat top 10 holders
3. RED FLAG jika:
   - 1 wallet pegang > 50% supply
   - Top 5 wallets pegang > 80% supply
   - Banyak wallet "dead address" di top holders
4. Gunakan tools:
   - bscscan.com/tokenholdercheck/{ADDRESS}

LANGKAH 4: TEST BUY & SELL
--------------------------
1. Gunakan PancakeSwap Testnet
2. Test swap kecil (0.01 BNB)
3. Coba JUAL kembali
4. Jika tidak bisa jual → HONEYPOT
5. Jika sell fee > 50% → SOFT RUG
6. Tools otomatis:
   - tokensniffer.com
   - honeypot.is
   - rugcheck.xyz

LANGKAH 5: CEK SOCIAL & TEAM
----------------------------
1. Website professional atau cuma landing page?
2. Social media aktif atau bot comments?
3. Team doxxed (identitas terbuka) atau anonim?
4. Audit report dari auditor terpercaya?
5. RED FLAG:
   - Website template murahan
   - Hanya punya Twitter, follower sedikit
   - Tidak ada audit
   - Team anonim tanpa track record

CHECKLIST AUDIT RAPID:
-----------------------
[ ] Source code verified di explorer?
[ ] Tidak ada fungsi mint() terbuka?
[ ] Tidak ada fungsi pause() / blacklist()?
[ ] Transfer fee < 10%?
[ ] LP terkunci minimal 6 bulan?
[ ] Top holder tidak pegang > 50%?
[ ] Bisa test buy & sell?
[ ] Tidak ada proxy pattern?
[ ] Tidak ada self-destruct?
[ ] Owner bukan contract address?

SKOR:
10/10 = Sangat aman, boleh invest
7-9/10 = Relatif aman, lakukan riset lebih lanjut
4-6/10 = Berisiko, investasi kecil saja
0-3/10 = SCAM, JANGAN INVESTASI!
*/
