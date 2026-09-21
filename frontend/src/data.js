export const contactData = [
  { id: 'asha', name: 'Asha Kumar', company: 'Aster Textiles', type: 'Customer', record: 'CUST-0042', channels: ['WhatsApp', 'Email'] },
  { id: 'arun', name: 'Arun Das', company: 'Operations', type: 'Employee', record: 'EMP-018', channels: ['Telegram', 'Email'] },
  { id: 'meera', name: 'Meera Shah', company: 'Willow Packaging', type: 'Supplier', record: 'SUP-012', channels: ['Email', 'WhatsApp'] },
]
export const threadData = [
  { id: 'c1', contact: 'asha', name: 'Asha Kumar', channel: 'WhatsApp', team: 'Sales', assignee: 'Priya N.', status: 'Open', bot: true, unread: 2, time: '2m', messages: [
    { text: 'Hi, can you check the dispatch date for SO-0248?', who: 'Asha Kumar', time: '10:41 AM' },
    { text: 'I have your order number. Let me check the latest update.', who: 'Order assistant', time: '10:41 AM', out: true },
    { text: 'I have emailed our updated delivery address.', who: 'Asha Kumar', time: '10:42 AM', channel: 'Email' },
    { text: 'Thank you. We need it by Friday.', who: 'Asha Kumar', time: '10:42 AM' },
  ] },
  { id: 'c2', contact: 'arun', name: 'Arun Das', channel: 'Telegram', team: 'People', assignee: 'Unassigned', status: 'Open', bot: true, unread: 1, time: '5m', messages: [
    { text: '/leave', who: 'Arun Das', time: '10:38 AM' },
    { text: 'What dates would you like to request?', who: 'Leave assistant', out: true, time: '10:38 AM' },
    { text: 'Monday and Tuesday next week.', who: 'Arun Das', time: '10:39 AM' },
  ] },
  { id: 'c3', contact: 'meera', name: 'Meera Shah', channel: 'Email', team: 'Support', assignee: 'You', status: 'Open', bot: false, unread: 0, time: '18m', subject: 'Revised packaging quotation', messages: [
    { text: 'Hello,\n\nHere is the revised quotation for your packaging requirements. Please let me know if you need any changes.\n\nRegards,\nMeera', who: 'Meera Shah', time: '10:26 AM' },
  ] },
  { id: 'c4', contact: null, name: '+91 •••••• 2048', channel: 'WhatsApp', team: 'Support', assignee: 'Unassigned', status: 'Open', bot: false, unread: 1, time: '21m', messages: [{ text: 'Hello, I wanted to ask about an order.', who: 'Unknown contact', time: '10:23 AM' }] },
]
export const teamData = [
  { name: 'Sales', members: [{ name: 'Sakthi', role: 'Manager' }, { name: 'Priya N.', role: 'Agent' }, { name: 'Ravi M.', role: 'Agent' }], channels: ['WhatsApp', 'Email'] },
  { name: 'Support', members: [{ name: 'Sakthi', role: 'Manager' }, { name: 'Meera S.', role: 'Agent' }], channels: ['WhatsApp', 'Telegram', 'Email'] },
  { name: 'People', members: [{ name: 'Sakthi', role: 'Manager' }, { name: 'Arun D.', role: 'Agent' }], channels: ['Telegram', 'Email'] },
]
export const flowData = [
  { id: 1, type: 'Trigger', label: '/order', icon: 'zap', field: 'Command', value: '/order' },
  { id: 2, type: 'Ask', label: 'Order number', icon: 'message-square', field: 'Question', value: 'What is your order number?' },
  { id: 3, type: 'Condition', label: 'Order number is valid', icon: 'git-branch', field: 'Condition', value: 'order_number is present and valid' },
  { id: 4, type: 'Action', label: 'Get order status', icon: 'play', field: 'Action', value: 'Read Sales Order' },
  { id: 5, type: 'Reply', label: 'Dispatch update', icon: 'corner-up-left', field: 'Message', value: 'Your order {{ order_number }}: {{ dispatch_status }}' },
]
