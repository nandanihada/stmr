// functions/index.js or functions/src/index.js

const functions = require("firebase-functions");
const admin = require("firebase-admin");

admin.initializeApp();
const db = admin.firestore();

exports.captureUserEmail = functions.https.onRequest(async (req, res) => {
  try {
    const {email} = req.body;

    if (!email) {
      return res.status(400).json({error: "Email is required"});
    }

    await db.collection("clickedUsers").add({
      email,
      timestamp: admin.firestore.FieldValue.serverTimestamp(),
    });

    return res.status(200).json({message: "Email saved successfully"});
  } catch (error) {
    console.error("Error saving email:", error);
    return res.status(500).json({error: "Internal Server Error"});
  }
});
