/**
 * ============================================================================
 * TverKar Campaign Auto-Update Google Apps Script
 * ============================================================================
 * Spreadsheet: https://docs.google.com/spreadsheets/d/1oOI6FGaXqfa_54vn7UV9FVLJrGTp3jmXRhJybYu5DfQ/edit?gid=1408716999
 * 
 * QUICK SETUP (1 Minute):
 * 1. Open your Google Sheet: https://docs.google.com/spreadsheets/d/1oOI6FGaXqfa_54vn7UV9FVLJrGTp3jmXRhJybYu5DfQ/edit?gid=1408716999
 * 2. In top menu click: Extensions > Apps Script
 * 3. Delete any code in Code.gs, paste this entire file into Code.gs, and click Save (💾).
 * 4. Click the blue "Deploy" button (top right) -> "New deployment".
 * 5. Click the gear icon (⚙) next to "Select type" -> select "Web app".
 * 6. Set:
 *    - Description: "TverKar Auto-Sync Webhook"
 *    - Execute as: "Me"
 *    - Who has access: "Anyone" (IMPORTANT!)
 * 7. Click "Deploy" and authorize access if prompted.
 * 8. Copy the generated "Web app URL" (starts with https://script.google.com/macros/s/...)
 * 9. Paste that URL into your .env file:
 *    GOOGLE_SHEET_WEBHOOK_URL=https://script.google.com/macros/s/.../exec
 * ============================================================================
 */

function doPost(e) {
  try {
    var ss = null;
    try {
      ss = SpreadsheetApp.getActiveSpreadsheet();
    } catch (e) {}
    if (!ss) {
      ss = SpreadsheetApp.openById("1oOI6FGaXqfa_54vn7UV9FVLJrGTp3jmXRhJybYu5DfQ");
    }
    var sheet = ss.getActiveSheet();
    
    var data = JSON.parse(e.postData.contents);
    
    var headers = [
      "Index", 
      "Timestamp", 
      "Phone (E.164)", 
      "Raw Phone", 
      "Candidate Name", 
      "Username", 
      "User ID", 
      "Consent Transfer", 
      "Employment Status", 
      "Job Preference / Urgency", 
      "Expected Salary", 
      "Preferred Location", 
      "Voice Notes", 
      "Dialogue Summary", 
      "Campaign Status", 
      "Notes", 
      "Workingna Admin URL", 
      "Migration Status", 
      "TverKar Worker ID"
    ];
    
    // Auto-create or ensure header row names are populated
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(headers);
    } else {
      var currentHeaders = sheet.getRange(1, 1, 1, headers.length).getValues()[0];
      var needsUpdate = false;
      for (var hIdx = 0; hIdx < headers.length; hIdx++) {
        if (!currentHeaders[hIdx] || currentHeaders[hIdx].toString().trim() === "") {
          currentHeaders[hIdx] = headers[hIdx];
          needsUpdate = true;
        }
      }
      if (needsUpdate) {
        sheet.getRange(1, 1, 1, headers.length).setValues([currentHeaders]);
      }
    }
    
    if (data.action === "bulk" && Array.isArray(data.rows)) {
      var rowsToAdd = [];
      for (var i = 0; i < data.rows.length; i++) {
        var r = data.rows[i];
        var rowArr = headers.map(function(h) {
          return r[h] !== undefined && r[h] !== null ? r[h] : "";
        });
        rowsToAdd.push(rowArr);
      }
      if (rowsToAdd.length > 0) {
        var startRow = sheet.getLastRow() + 1;
        sheet.getRange(startRow, 1, rowsToAdd.length, headers.length).setValues(rowsToAdd);
      }
      return ContentService.createTextOutput(JSON.stringify({
        status: "success",
        action: "bulk",
        inserted: rowsToAdd.length
      })).setMimeType(ContentService.MimeType.JSON);
    } else {
      var r = data.row || data;
      var rowArr = headers.map(function(h) {
        return r[h] !== undefined && r[h] !== null ? r[h] : "";
      });
      sheet.appendRow(rowArr);
      return ContentService.createTextOutput(JSON.stringify({
        status: "success",
        action: "append",
        row: sheet.getLastRow()
      })).setMimeType(ContentService.MimeType.JSON);
    }
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      error: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  return ContentService.createTextOutput(JSON.stringify({
    status: "online",
    message: "TverKar Google Sheet Webhook is ready and listening for campaign updates!"
  })).setMimeType(ContentService.MimeType.JSON);
}
