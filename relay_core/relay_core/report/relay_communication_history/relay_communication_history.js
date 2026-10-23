frappe.query_reports["Relay Communication History"] = {
  filters: [
    {fieldname:"report_mode",label:__("Report contents"),fieldtype:"Select",options:["Full messages","Daily summary"],default:"Full messages",reqd:1},
    {fieldname:"include_images",label:__("Include image previews"),fieldtype:"Check",default:0},
    {fieldname:"output_format",label:__("File format"),fieldtype:"Select",options:["PDF","Excel"],default:"PDF",reqd:1},
    {fieldname:"business_doctype",label:__("Business type"),fieldtype:"Link",options:"DocType",reqd:1},
    {fieldname:"business_name",label:__("Business record"),fieldtype:"Dynamic Link",options:"business_doctype",reqd:1},
    {fieldname:"from_date",label:__("From date"),fieldtype:"Date",reqd:1},
    {fieldname:"to_date",label:__("To date"),fieldtype:"Date",reqd:1}
  ]
};
