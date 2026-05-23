# Blockchain Land Registry System

A secure land property registry with blockchain verification and AI-powered fraud detection. This system combines FastAPI backend, PostgreSQL database, Hardhat blockchain integration, and intelligent fraud analysis.

## 🎯 Features

- **User Management**: Register and manage owners, government officials, and admin accounts
- **Property Management**: Register properties, transfer ownership, and dispute resolution
- **Blockchain Integration**: Immutable audit trails on local Hardhat network (or Sepolia testnet)
- **AI Fraud Detection**: Detects 6 fraud patterns including amount anomalies, circular ownership, rapid transfers, price manipulation, self-dealing, and high-frequency transactions
- **PostgreSQL Database**: Persistent data storage with SQLAlchemy ORM
- **JWT Authentication**: Secure token-based user authentication
- **Admin Dashboard**: Comprehensive fraud analysis and system management

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | FastAPI, SQLAlchemy, PostgreSQL |
| **Blockchain** | Solidity, Web3.py, Hardhat, OpenZeppelin |
| **Frontend** | HTML5, CSS3, JavaScript (Vanilla) |
| **Auth** | JWT (python-jose), PBKDF2 Password Hashing |
| **Database** | PostgreSQL 12+ |

## 📋 Prerequisites

- **Python**: 3.11 or higher
- **Node.js**: 22.13+ (for Hardhat compatibility)
- **npm**: 9+
- **PostgreSQL**: 12 or higher
- **Git**: For version control

## 🚀 Quick Start (A-Z Instructions)

### Step 1: Clone from GitHub

```bash
git clone https://github.com/YOUR_USERNAME/land-registry-system.git
cd land-registry-system
```

### Step 2: Setup Python Backend

#### Windows
```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

#### Mac/Linux
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 3: Setup PostgreSQL Database

#### Option A: Using psql (Command Line)
```bash
psql -U postgres
CREATE DATABASE land_registry_db;
\q
```

#### Option B: Using PgAdmin (GUI)
1. Open PgAdmin
2. Create new database: `land_registry_db`
3. Owner: `postgres`

### Step 4: Configure Backend Environment

1. Navigate to `backend/` folder
2. Open `.env` file
3. Update database credentials if needed:
   ```
   DB_USER=postgres
   DB_PASSWORD=your_password
   DB_HOST=localhost
   DB_PORT=5432
   DB_NAME=land_registry_db
   DATABASE_URL=postgresql://postgres:your_password@localhost:5432/land_registry_db
   ```

4. Keep blockchain settings as default (local Hardhat):
   ```
   SEPOLIA_RPC_URL=http://127.0.0.1:8545
   CONTRACT_ADDRESS=0x5FbDB2315678afecb367f032d93F642f64180aa3
   PRIVATE_KEY=your_hardhat_private_key_here
   ```

5. Auth secrets (keep default or customize):
   ```
   SECRET_KEY=your_secret_key_here
   ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=30
   TOKEN_EXPIRE_HOURS=12
   ```

### Step 5: Populate Database with Test Data

```bash
cd backend
python seed.py
```

This creates:
- 12 test users (admin, government, 10 owners)
- 8 properties
- 24 transactions with fraud patterns

### Step 6: Setup Blockchain (Hardhat)

```bash
cd blockchain
npm ci
```

### Step 7: Start All Services

**You need 4 terminals open simultaneously:**

#### Terminal 1: Backend (Port 8000)
```bash
cd backend
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```
✅ Access API docs: `http://127.0.0.1:8000/docs`

#### Terminal 2: Hardhat Blockchain Node (Port 8545)
```bash
cd blockchain
set CI=true
npx hardhat node
```
✅ Wait for: `Started HTTP and WebSocket JSON-RPC server at http://127.0.0.1:8545/`

#### Terminal 3: Deploy Smart Contract
```bash
cd blockchain
npx hardhat run scripts/deploy.js --network localhost
```
✅ Wait for: `✅ LandRegistry deployed to: 0x5FbDB2315678afecb367f032d93F642f64180aa3`

#### Terminal 4: Frontend (Port 5500)
```bash
cd frontend
python -m http.server 5500
```
✅ Open: `http://127.0.0.1:5500/login.html`

### Step 8: Login and Explore

Use test credentials:

| Role | Email | Password |
|------|-------|----------|
| Admin | `admin@blrs.com` | `admin123` |
| Government | `gov@blrs.com` | `gov123` |
| Owner 1 | `arjun@test.com` | `pass123` |
| Owner 2 | `priya@test.com` | `pass123` |
| Owner 3 | `ravi@test.com` | `pass123` |

## 📚 Project Structure

```
land-registry-system/
├── backend/                    # FastAPI Backend
│   ├── auth.py                # JWT authentication
│   ├── database.py            # SQLAlchemy ORM setup
│   ├── models.py              # Database models
│   ├── schemas.py             # Pydantic schemas
│   ├── main.py                # FastAPI app & routes
│   ├── blockchain_connector.py # Web3 integration
│   ├── fraud_detection.py     # AI fraud analysis
│   ├── seed.py                # Database seeder
│   ├── requirements.txt        # Python dependencies
│   └── .env                   # Configuration (don't share)
│
├── blockchain/                # Hardhat Smart Contracts
│   ├── contracts/
│   │   └── LandRegistry.sol   # Main smart contract
│   ├── scripts/
│   │   └── deploy.js          # Deployment script
│   ├── hardhat.config.js      # Hardhat configuration
│   ├── package.json           # Node.js dependencies
│   └── .env                   # Blockchain config
│
├── frontend/                  # Web Interface
│   ├── login.html             # Login page
│   ├── register.html          # Registration page
│   ├── dashboard.html         # Owner dashboard
│   ├── admin_dashboard.html   # Admin panel
│   ├── gov_dashboard.html     # Government panel
│   └── styles/                # CSS files
│
└── README.md                  # This file
```

## 🔑 Key API Endpoints

### Authentication
- `POST /users/register` — Register new user
- `POST /users/login` — Login and get JWT token
- `GET /users/me` — Get current user info

### Properties
- `POST /properties/request` — Request new property registration
- `GET /properties` — List all properties
- `POST /properties/{id}/transfer` — Transfer property ownership
- `POST /properties/{id}/dispute` — Raise dispute on property

### Fraud Detection
- `POST /fraud/analyze` — Run AI fraud analysis (Admin/Government only)
- `GET /fraud/alerts` — Get fraud alerts
- `GET /fraud/transactions/{id}` — Check transaction risk

### Blockchain
- `GET /blockchain/stats` — Blockchain network statistics
- `GET /properties/{id}/audit-trail` — Property blockchain history

Full API documentation available at `http://127.0.0.1:8000/docs` after starting backend.

## 🧠 AI Fraud Detection

The system detects **6 fraud patterns**:

1. **Amount Anomaly** (DBSCAN clustering)
   - Transactions with suspiciously high amounts
   - Example: Property worth ₹80L suddenly sells for ₹400L

2. **Circular Ownership** (Louvain community detection)
   - A → B → C → A ownership chains
   - Indicates collusion between users

3. **Rapid Transfer**
   - Property sold multiple times within 2 days
   - Sign of money laundering

4. **Price Manipulation**
   - Property price jumps 5x in one transfer
   - Artificial value inflation

5. **Self-Dealing**
   - Same person using multiple wallet addresses
   - Circumventing transfer restrictions

6. **High-Frequency Pair**
   - Same two users transact >3 times
   - Suspicious recurring pattern

Run analysis: Login as Admin/Government → Fraud Detection → Run Full Analysis

## 🔐 Security Features

- **Password Hashing**: PBKDF2-SHA256 (resistant to GPU attacks)
- **JWT Tokens**: 12-hour expiration for session management
- **Database Constraints**: Unique emails and wallets prevent duplicates
- **CORS Enabled**: Secure cross-origin requests
- **Role-Based Access**: OWNER, GOVERNMENT, ADMIN roles
- **Blockchain Immutability**: All transactions recorded on-chain

## 🐛 Troubleshooting

### Backend Won't Start

**Error**: `ModuleNotFoundError: No module named 'backend'`
- **Fix**: Ensure you run `uvicorn` from project root, not from `backend/` folder
- Run from: `the root folder of the project (land-registry-system/)`

**Error**: `psycopg2.OperationalError: could not connect to server`
- **Fix**: PostgreSQL is not running or credentials are wrong
- Check `backend/.env` database credentials
- Ensure `land_registry_db` database exists
- Restart PostgreSQL service

**Error**: `No Hardhat config file found`
- **Fix**: Run Hardhat commands from `blockchain/` folder only
- Correct: `cd blockchain && npx hardhat node`
- Incorrect: `npx hardhat node` (from other folders)

### Blockchain Issues

**Error**: `listen EADDRINUSE: address already in use 127.0.0.1:8545`
- **Fix**: Port 8545 is already in use
- Option 1: Close existing Hardhat node (CTRL+C in that terminal)
- Option 2: Use different port: `npx hardhat node --port 8546`

**Error**: `You are using Node.js 22.x which is not supported by Hardhat`
- **Fix**: Use Node.js 20.x LTS
- Download from: https://nodejs.org/
- Verify: `node --version` should show `v20.x.x`

### Frontend Connection Issues

**Error**: `CORS error or "failed to fetch"`
- **Fix**: Ensure backend is running on `http://127.0.0.1:8000`
- Check if CORS is enabled in `backend/main.py`
- Ensure frontend URL is `http://127.0.0.1:5500` (not `file://`)

**Error**: Blank page or cannot register
- **Fix**: Open browser console (F12) to see errors
- Check if backend API is running and accessible
- Try clearing browser cache (CTRL+SHIFT+DELETE)

## 📖 Usage Guide

### Workflow 1: Register New Property

1. Login as **Owner** (e.g., `arjun@test.com`)
2. Dashboard → "Register New Property"
3. Fill details: type, address, area, price
4. Submit request
5. Login as **Government** → Approve request
6. Property is now registered and on blockchain

### Workflow 2: Transfer Property

1. Login as **Owner 1** (property owner)
2. Dashboard → "My Properties" → Select property
3. Click "Transfer Property"
4. Enter **Owner 2's user ID** and transfer amount
5. Click "Confirm Transfer"
6. Transaction is recorded on blockchain
7. Ownership updates immediately

### Workflow 3: Detect Fraud

1. Seed database with test data: `python seed.py`
2. Login as **Admin** or **Government**
3. Dashboard → "Fraud Detection"
4. Click "Run Full Analysis"
5. View results: All 6 fraud patterns should be detected
6. Click on alerts to see details

### Workflow 4: Raise Dispute

1. Login as **Government**
2. Dashboard → "Disputed Properties"
3. Select property and click "Raise Dispute"
4. Blockchain records dispute
5. Admin can view and resolve

## 🛑 Stopping the Project

To properly exit:

```bash
# In each terminal running a service, press:
CTRL + C
```

This will gracefully shut down:
- Backend server
- Hardhat node
- Frontend server
- Any database connections

## 🚀 Next Steps (Future Enhancements)

- [ ] React/Vue frontend for better UX
- [ ] Mobile app (React Native)
- [ ] Deploy to Sepolia testnet
- [ ] Advanced analytics dashboard
- [ ] Email notifications
- [ ] Multi-chain support
- [ ] Integration with government databases

## 📝 Environment Variables

### backend/.env
```
# Database
DB_USER=postgres
DB_PASSWORD=your_db_password_here
DB_HOST=localhost
DB_PORT=5432
DB_NAME=land_registry_db
DATABASE_URL=postgresql://postgres:your_db_password_here@localhost:5432/land_registry_db

SEPOLIA_RPC_URL=http://127.0.0.1:8545
CONTRACT_ADDRESS=your_deployed_contract_address
PRIVATE_KEY=your_hardhat_private_key_here

SECRET_KEY=your_secret_key_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
TOKEN_EXPIRE_HOURS=12
```

**⚠️ IMPORTANT**: Never commit `.env` file to GitHub. Add to `.gitignore`.

## 📄 Database Schema

### users
- `user_id` (PK)
- `full_name`, `email`, `password_hash`
- `role` (OWNER, GOVERNMENT, ADMIN)
- `wallet_address`
- `is_active`, `created_at`

### properties
- `property_id` (PK)
- `registration_number`, `property_type`
- `address`, `area_sqft`, `price`
- `current_owner_id` (FK)
- `status` (REGISTERED, TRANSFERRED, DISPUTED)
- `blockchain_tx_hash`, `is_on_chain`
- `created_at`

### transactions
- `transaction_id` (PK)
- `property_id` (FK), `sender_id` (FK), `receiver_id` (FK)
- `amount`, `payment_mode`
- `blockchain_tx_hash`
- `created_at`

### fraud_alerts
- `alert_id` (PK)
- `transaction_id` (FK)
- `fraud_type` (AMOUNT_ANOMALY, CIRCULAR_OWNERSHIP, etc.)
- `risk_score` (0-100)
- `flagged_user_id` (FK)
- `status` (OPEN, RESOLVED)

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit changes: `git commit -m "Add your feature"`
4. Push: `git push origin feature/your-feature`
5. Submit a pull request

## 📞 Support

If you encounter issues:
1. Check the **Troubleshooting** section above
2. Review browser console (F12) for frontend errors
3. Check terminal logs for backend errors
4. Ensure all 4 services are running
5. Verify PostgreSQL and Node.js versions

## 📜 License

MIT License - Feel free to use this project for educational and personal purposes.

## 👤 Author

**Geetesh Muralitharan & Giricharan BV**
- GitHub: [@geeteshkm](https://github.com/geeteshkm)
- Email [Geetesh]: geeteshkm25@gmail.com
- Email [Giricharan]: giribv1612@gmail.com
- LinkedIn: [Geetesh M](https://www.linkedin.com/in/geeteshkm/)
- LinkedIn: [Giricharan BV](https://www.linkedin.com/in/giri-charan-8001282a0/)

---

**Last Updated**: May 2026
**Version**: 2.0.0

⭐ If this project helped you, please consider giving it a star on GitHub!
