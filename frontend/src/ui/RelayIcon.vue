<script setup>
import { computed } from 'vue'
import {
  Activity, AlertCircle, ArrowDown, ArrowLeft, ArrowUpRight, Bell, Bookmark, Bot, Briefcase, Building2, Check, ChevronDown, ChevronRight,
  Circle, ClipboardList, Clock, Copy, CreditCard, CornerUpLeft, Crosshair, Download, ExternalLink, Eye, File, FileText,
  Filter, Forward, GitBranch, Globe, Grid, Image, Inbox, Info, Languages, Link, List, LoaderCircle, Lock,
  LogOut, Mail, MapPin, Megaphone, Menu, MessageCircle, MessageSquare, Mic, MicOff, Monitor, Moon, MoreHorizontal,
  MoreVertical, Music, PanelRight, Paperclip, PenLine, Phone, PhoneOff, Pin, Play, Plus, Radio, RefreshCw,
  Repeat, Reply, Scan, Search, Send, Settings, Smile, Sparkles, Square, SquareCheck, Star, Sun, Trash, Truck, Upload, User,
  UserCheck, Users, Video, WandSparkles, X, Zap,
} from '@lucide/vue'

const props = defineProps({ name: { type: String, default: 'circle' }, size: { type: [String, Number], default: 16 } })
const icons = { Activity, AlertCircle, ArrowDown, ArrowLeft, ArrowUpRight, Bell, Bookmark, Bot, Briefcase, Building2, Check, ChevronDown, ChevronRight, Circle, ClipboardList, Clock, Copy, CreditCard, CornerUpLeft, Crosshair, Download, ExternalLink, Eye, File, FileText, Filter, Forward, GitBranch, Globe, Grid, Image, Inbox, Info, Languages, Link, List, LoaderCircle, Lock, LogOut, Mail, MapPin, Megaphone, Menu, MessageCircle, MessageSquare, Mic, MicOff, Monitor, Moon, MoreHorizontal, MoreVertical, Music, PanelRight, Paperclip, PenLine, Phone, PhoneOff, Pin, Play, Plus, Radio, RefreshCw, Repeat, Reply, Scan, Search, Send, Settings, Smile, Sparkles, Square, SquareCheck, Star, Sun, Trash, Truck, Upload, User, UserCheck, Users, Video, WandSparkles, X, Zap }
const aliases = { actions: 'WandSparkles', scope: 'Crosshair', viewport: 'Scan', sidebar: 'PanelRight', menu: 'Menu', 'log-out': 'LogOut', 'check-square': 'SquareCheck', 'edit-3': 'PenLine', building: 'Building2' }
const component = computed(() => {
  const pascal = props.name.split('-').map(part => part.charAt(0).toUpperCase() + part.slice(1)).join('')
  return icons[aliases[props.name] || pascal] || icons.Circle
})
</script>

<template><component :is="component" :size="size" :stroke-width="1.7" aria-hidden="true" /></template>
