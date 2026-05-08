const hre = require("hardhat");
const fs  = require("fs");
const path = require("path");

async function main() {

  console.log("Deploying LandRegistry contract...");
  console.log("Network:", hre.network.name);

  const [deployer] = await hre.ethers.getSigners();
  console.log("Deploying with account:", deployer.address);

  const balance = await deployer.getBalance();
  console.log("Account balance:", hre.ethers.utils.formatEther(balance), "ETH");

  // Deploy
  const LandRegistry = await hre.ethers.getContractFactory("LandRegistry");
  const contract     = await LandRegistry.deploy();
  await contract.deployed();

  console.log("\n✅ LandRegistry deployed to:", contract.address);
  console.log("Transaction hash:", contract.deployTransaction.hash);

  // Save address to .env.deployed for backend use
  const envContent = `CONTRACT_ADDRESS=${contract.address}\n`;
  fs.writeFileSync(
    path.join(__dirname, "../.env.deployed"),
    envContent
  );
  console.log("\n📄 Contract address saved to .env.deployed");
  console.log("👉 Copy CONTRACT_ADDRESS to your backend .env file");

  // Verify on Etherscan (optional, works on Sepolia)
  if (hre.network.name === "sepolia") {
    console.log("\nWaiting 30s before Etherscan verification...");
    await new Promise(r => setTimeout(r, 30000));
    try {
      await hre.run("verify:verify", {
        address: contract.address,
        constructorArguments: [],
      });
      console.log("✅ Contract verified on Etherscan");
    } catch (e) {
      console.log("⚠️  Etherscan verification failed:", e.message);
    }
  }
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error("❌ Deployment failed:", error);
    process.exit(1);
  });
