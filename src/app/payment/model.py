# "use client";

# import React, { useState, useEffect, useRef, useCallback } from "react";
# import {
#   X,
#   Send,
#   ChevronLeft,
#   Plus,
#   Loader2,
#   CheckCircle2,
#   Clock,
#   ChevronDown,
#   Ticket,
#   HeadphonesIcon,
#   Inbox,
#   Lock,
#   Sparkles,
#   Check,
# } from "lucide-react";
# import { motion, AnimatePresence } from "framer-motion";
# import { auth } from "@/lib/firebase";

# const API = process.env.NEXT_PUBLIC_API_URL;

# // ─── helpers ──────────────────────────────────────────────────────────────────
# const statusMeta = {
#   open: { label: "Open", color: "#22c55e", Icon: CheckCircle2 },
#   in_progress: { label: "In Progress", color: "#f59e0b", Icon: Clock },
#   closed: { label: "Closed", color: "#94a3b8", Icon: CheckCircle2 },
# };

# function StatusBadge({ status }) {
#   const m = statusMeta[status] ?? statusMeta.open;
#   return (
#     <span
#       className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
#       style={{
#         background: `${m.color}20`,
#         color: m.color,
#         border: `1px solid ${m.color}40`,
#       }}
#     >
#       {m.label}
#     </span>
#   );
# }

# function fmt(iso) {
#   return new Date(iso).toLocaleString([], {
#     month: "short",
#     day: "numeric",
#     hour: "2-digit",
#     minute: "2-digit",
#   });
# }

# function getSubjectPlaceholder(team) {
#   if (!team) return "Brief summary of your issue… (optional)";
#   const slug = (team.slug || "").toLowerCase();
#   if (slug === "auth")
#     return "e.g. Can't log in, password reset not working… (optional)";
#   if (slug === "ai" || slug === "ai-team")
#     return "e.g. AI giving wrong results, slow responses… (optional)";
#   if (slug === "payment" || slug === "payments")
#     return "e.g. Payment failed, charged twice, refund… (optional)";
#   return "Brief summary of your issue… (optional)";
# }

# function getMessagePlaceholder(team) {
#   if (!team) return "Tell us what's happening…";
#   const slug = (team.slug || "").toLowerCase();
#   if (slug === "auth")
#     return "Describe your authentication issue in detail — what happens when you try to log in?";
#   if (slug === "ai" || slug === "ai-team")
#     return "Describe the AI issue — what query did you run and what was the unexpected output?";
#   if (slug === "payment" || slug === "payments")
#     return "Describe your payment issue — include any error messages or transaction references.";
#   return "Tell us what's happening — the more detail, the faster we can help!";
# }

# // ─── Main component ───────────────────────────────────────────────────────────
# export default function TicketChatPopup({ hasUnread, setHasUnread }) {
#   const [open, setOpen] = useState(false);
#   const [view, setView] = useState("list");
#   const [tickets, setTickets] = useState([]);
#   const [activeTicket, setActive] = useState(null);
#   const [loading, setLoading] = useState(false);
#   const [sending, setSending] = useState(false);
#   const [msg, setMsg] = useState("");
#   const [userEmail, setUserEmail] = useState(null);
#   const [userName, setUserName] = useState(null);

#   // new-ticket form
#   const [newSubject, setNewSubject] = useState("");
#   const [newMsg, setNewMsg] = useState("");
#   const [newTeam, setNewTeam] = useState(null);
#   const [typeOpen, setTypeOpen] = useState(false);
#   const [creating, setCreating] = useState(false);

#   // teams fetched from backend
#   const [teams, setTeams] = useState([]);
#   const [teamsLoading, setTeamsLoading] = useState(false);

#   const bottomRef = useRef(null);
#   const inputRef = useRef(null);
#   const activeTicketRef = useRef(activeTicket);

#   useEffect(() => {
#     activeTicketRef.current = activeTicket;
#   }, [activeTicket]);

#   // ── Firebase auth ──────────────────────────────────────────────────────────
#   useEffect(() => {
#     const unsubscribe = auth.onAuthStateChanged((u) => {
#       if (u) {
#         setUserEmail(u.email);
#         setUserName(u.displayName || u.email?.split("@")[0] || "User");
#       }
#     });
#     return unsubscribe;
#   }, []);

#   // ── Fetch active teams ─────────────────────────────────────────────────────
#   const fetchTeams = useCallback(async () => {
#     setTeamsLoading(true);
#     try {
#       const res = await fetch(`${API}/user/tickets/teams/active`);
#       const data = await res.json();
#       setTeams(data);
#       if (data.length > 0) setNewTeam(data[0]);
#     } catch {
#       // silently swallow
#     } finally {
#       setTeamsLoading(false);
#     }
#   }, []);

#   useEffect(() => {
#     if (view !== "new" || teams.length > 0) return;
#     void (async () => {
#       await fetchTeams();
#     })();
#   }, [view, teams.length, fetchTeams]);

#   // ── Fetch tickets ──────────────────────────────────────────────────────────
#   const fetchTickets = useCallback(
#     async (silent = false) => {
#       if (!userEmail) return;
#       if (!silent) setLoading(true);
#       try {
#         const res = await fetch(
#           `${API}/user/tickets/?email=${encodeURIComponent(userEmail)}`,
#           // `${API}/tickets`,
#         );
#         const data = await res.json();
#         console.log('tickets: ', data);

#         setTickets(data);
#         setHasUnread(() => {
#           if (open) return false;
#           return data.some((t) => t.replies?.some((r) => r.is_admin === 1));
#         });
#         const current = activeTicketRef.current;
#         if (current) {
#           const fresh = data.find((t) => t.id === current.id);
#           if (fresh) setActive(fresh);
#         }
#       } catch {
#         // silently swallow
#       } finally {
#         if (!silent) setLoading(false);
#       }
#     },
#     [userEmail, setHasUnread, open],
#   );

#   // Fetch only when the popup opens
#   useEffect(() => {
#     if (!open || !userEmail) return;
#     void (async () => {
#       await fetchTickets();
#     })();
#   }, [open, userEmail, fetchTickets]);

#   // Scroll to bottom on new messages
#   useEffect(() => {
#     bottomRef.current?.scrollIntoView({ behavior: "smooth" });
#   }, [activeTicket?.replies]);

#   // Focus input when entering chat
#   useEffect(() => {
#     if (view !== "chat") return;
#     const t = setTimeout(() => inputRef.current?.focus(), 150);
#     return () => clearTimeout(t);
#   }, [view]);

#   // ── Toggle open — clears unread dot instantly on open ─────────────────────
#   const handleToggleOpen = useCallback(() => {
#     setOpen((prev) => {
#       if (!prev) setHasUnread(false);
#       return !prev;
#     });
#   }, [setHasUnread]);

#   // ── Close — clears unread dot too ─────────────────────────────────────────
#   const handleClose = useCallback(() => {
#     setOpen(false);
#     setHasUnread(false);
#   }, [setHasUnread]);

#   // ── Open ticket ────────────────────────────────────────────────────────────
#   const openTicket = useCallback((t) => {
#     setActive(t);
#     setView("chat");
#   }, []);

#   // ── Send reply — optimistic: show bubble instantly, clear input, then confirm ──
#   const sendReply = useCallback(async () => {
#     if (!msg.trim() || !activeTicket || sending) return;

#     const tempId = `temp-${Date.now()}`;
#     const msgToSend = msg.trim();

#     // clear input immediately
#     setMsg("");

#     // optimistic bubble
#     setActive((prev) =>
#       prev
#         ? {
#             ...prev,
#             replies: [
#               ...(prev.replies ?? []),
#               {
#                 id: tempId,
#                 message: msgToSend,
#                 is_admin: 0,
#                 reply_type: "user",
#                 created_at: new Date().toISOString(),
#                 pending: true,
#               },
#             ],
#           }
#         : prev,
#     );

#     setSending(true);

#     try {
#       const res = await fetch(
#         `${API}/user/tickets/${activeTicket.id}/reply?email=${encodeURIComponent(userEmail)}`,
#         {
#           method: "POST",
#           headers: { "Content-Type": "application/json" },
#           body: JSON.stringify({ message: msgToSend }),
#         },
#       );

#       console.log('tickets: ', res);

#       if (!res.ok) {
#         throw new Error("Failed to send reply");
#       }

#       // Some APIs return partial ticket data, so refetch the full list instead
#       await fetchTickets(true);
#     } catch (error) {
#       // remove optimistic bubble on failure
#       setActive((prev) =>
#         prev
#           ? {
#               ...prev,
#               replies: (prev.replies ?? []).filter((r) => r.id !== tempId),
#             }
#           : prev,
#       );

#       // restore typed message so user does not lose it
#       setMsg(msgToSend);
#     } finally {
#       setSending(false);
#     }
#   }, [msg, activeTicket, sending, userEmail, fetchTickets]);

#   // ── Create ticket ──────────────────────────────────────────────────────────
#   const createTicket = useCallback(async () => {
#     if (!newMsg.trim() || !newTeam || creating) return;
#     setCreating(true);
#     try {
#       const res = await fetch(`${API}/user/tickets/`, {
#         method: "POST",
#         headers: { "Content-Type": "application/json" },
#         body: JSON.stringify({
#           subject: newSubject.trim() || `${newTeam.name} support request`,
#           message: newMsg.trim(),
#           user_email: userEmail,
#           user_name: userName,
#           ticket_type: newTeam.slug,
#           user_plan: "free",
#         }),
#       });
#       const ticket = await res.json();
#       setTickets((prev) => [ticket, ...prev]);
#       setNewSubject("");
#       setNewMsg("");
#       setNewTeam(teams[0] ?? null);
#       setActive(ticket);
#       setView("chat");
#     } catch {
#       // swallow
#     } finally {
#       setCreating(false);
#     }
#   }, [newSubject, newMsg, creating, userEmail, userName, newTeam, teams]);

#   // ── Go to new ticket from closed state ────────────────────────────────────
#   const raiseNewTicket = useCallback(() => {
#     setActive(null);
#     setNewSubject("");
#     setNewMsg("");
#     if (teams.length > 0) setNewTeam(teams[0]);
#     setView("new");
#   }, [teams]);

#   return (
#     <>
#       <AnimatePresence>
#         {open && (
#           <motion.div
#             initial={{ opacity: 0, y: 20, scale: 0.96 }}
#             animate={{ opacity: 1, y: 0, scale: 1 }}
#             exit={{ opacity: 0, y: 20, scale: 0.96 }}
#             transition={{ duration: 0.22, ease: "easeOut" }}
#             className="fixed bottom-20 left-4 z-[200] flex flex-col shadow-2xl overflow-hidden"
#             style={{
#               width: 360,
#               height: 520,
#               backgroundColor: "var(--sidebar-bg)",
#               border: "1px solid var(--sidebar-border)",
#               borderRadius: 16,
#             }}
#           >
#             {/* Header */}
#             <div
#               className="flex items-center justify-between px-4 py-3 shrink-0"
#               style={{
#                 borderBottom: "1px solid var(--sidebar-border)",
#                 background:
#                   "linear-gradient(135deg, color-mix(in srgb, var(--primary) 10%, transparent), color-mix(in srgb, var(--accent) 8%, transparent))",
#               }}
#             >
#               <div className="flex items-center gap-2.5">
#                 {view !== "list" && (
#                   <button
#                     onClick={() => {
#                       setView("list");
#                       setActive(null);
#                     }}
#                     className="p-1 rounded-md hover:bg-white/10 transition-colors"
#                     style={{ color: "var(--text-muted)" }}
#                   >
#                     <ChevronLeft size={16} />
#                   </button>
#                 )}
#                 <HeadphonesIcon size={16} style={{ color: "var(--primary)" }} />
#                 <span
#                   className="text-sm font-bold"
#                   style={{ color: "var(--text-main)" }}
#                 >
#                   {view === "list"
#                     ? "Support"
#                     : view === "new"
#                       ? "New Ticket"
#                       : (activeTicket?.ticket_id ?? "Chat")}
#                 </span>
#                 {view === "chat" && activeTicket && (
#                   <StatusBadge status={activeTicket.status} />
#                 )}
#               </div>

#               <div className="flex items-center gap-2">
#                 {view === "list" && (
#                   <button
#                     onClick={() => setView("new")}
#                     className="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold transition-all"
#                     style={{ background: "var(--primary)", color: "white" }}
#                   >
#                     <Plus size={12} />
#                     New
#                   </button>
#                 )}
#                 <button
#                   onClick={handleClose}
#                   className="p-1.5 rounded-md hover:bg-white/10 transition-colors"
#                   style={{ color: "var(--text-muted)" }}
#                 >
#                   <X size={15} />
#                 </button>
#               </div>
#             </div>

#             {/* Body */}
#             <div className="flex-1 overflow-hidden flex flex-col">
#               {/* ── LIST VIEW ─────────────────────────────────────────────── */}
#               {view === "list" && (
#                 <div className="flex-1 overflow-y-auto p-3 space-y-2">
#                   {loading ? (
#                     <div className="flex items-center justify-center h-full">
#                       <Loader2
#                         size={22}
#                         className="animate-spin"
#                         style={{ color: "var(--primary)" }}
#                       />
#                     </div>
#                   ) : tickets?.length === 0 ? (
#                     <div className="flex flex-col items-center justify-center h-full gap-3 py-8">
#                       <div
#                         className="w-14 h-14 rounded-2xl flex items-center justify-center"
#                         style={{
#                           background:
#                             "color-mix(in srgb, var(--primary) 12%, transparent)",
#                         }}
#                       >
#                         <Inbox size={24} style={{ color: "var(--primary)" }} />
#                       </div>
#                       <p
#                         className="text-xs font-semibold text-center"
#                         style={{ color: "var(--text-muted)" }}
#                       >
#                         No tickets yet.
#                         <br />
#                         Raise one if you need help!
#                       </p>
#                       <button
#                         onClick={() => setView("new")}
#                         className="px-4 py-2 rounded-lg text-xs font-bold transition-all"
#                         style={{ background: "var(--primary)", color: "white" }}
#                       >
#                         + Raise a Ticket
#                       </button>
#                     </div>
#                   ) : (
#                     tickets?.map((t) => {
#                       const lastReply = t.replies?.[t.replies.length - 1];
#                       const hasAdminReply = t.replies?.some(
#                         (r) => r.is_admin === 1,
#                       );
#                       const preview = lastReply
#                         ? (lastReply.is_admin ? "Support: " : "You: ") +
#                           lastReply.message.slice(0, 40)
#                         : t.message.slice(0, 40);
#                       const tooLong =
#                         (lastReply?.message ?? t.message).length > 40;

#                       return (
#                         <button
#                           key={t.id}
#                           onClick={() => openTicket(t)}
#                           className="w-full text-left rounded-xl p-3 transition-all"
#                           style={{
#                             background:
#                               "color-mix(in srgb, var(--primary) 5%, transparent)",
#                             border: "1px solid var(--sidebar-border)",
#                           }}
#                         >
#                           <div className="flex items-start justify-between gap-2 mb-1.5">
#                             <span
#                               className="text-xs font-bold truncate flex-1"
#                               style={{ color: "var(--text-main)" }}
#                             >
#                               {t.subject}
#                             </span>
#                             <div className="flex items-center gap-1.5 shrink-0">
#                               {hasAdminReply && (
#                                 <span className="w-2 h-2 rounded-full bg-red-500 shrink-0" />
#                               )}
#                               <StatusBadge status={t.status} />
#                             </div>
#                           </div>
#                           <div className="flex items-center justify-between">
#                             <span
#                               className="text-[10px] truncate max-w-[70%]"
#                               style={{ color: "var(--text-muted)" }}
#                             >
#                               {preview}
#                               {tooLong ? "…" : ""}
#                             </span>
#                             <span
#                               className="text-[9px] shrink-0 ml-2"
#                               style={{ color: "var(--sidebar-muted)" }}
#                             >
#                               {fmt(t.updated_at)}
#                             </span>
#                           </div>
#                         </button>
#                       );
#                     })
#                   )}
#                 </div>
#               )}

#               {/* ── NEW TICKET VIEW ───────────────────────────────────────── */}
#               {view === "new" && (
#                 <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
#                   <div>
#                     <label
#                       className="block text-[10px] font-bold uppercase tracking-widest mb-1.5"
#                       style={{ color: "var(--sidebar-muted)" }}
#                     >
#                       Subject
#                     </label>
#                     <input
#                       required
#                       value={newSubject}
#                       onChange={(e) => setNewSubject(e.target.value)}
#                       placeholder={getSubjectPlaceholder(newTeam)}
#                       className="w-full px-3 py-2.5 rounded-lg text-sm outline-none"
#                       style={{
#                         background:
#                           "color-mix(in srgb, var(--primary) 6%, transparent)",
#                         border: "1px solid var(--sidebar-border)",
#                         color: "var(--text-main)",
#                       }}
#                     />
#                   </div>

#                   <div className="flex-1">
#                     <label
#                       className="block text-[10px] font-bold uppercase tracking-widest mb-1.5"
#                       style={{ color: "var(--sidebar-muted)" }}
#                     >
#                       Describe your issue
#                     </label>
#                     <textarea
#                       value={newMsg}
#                       onChange={(e) => setNewMsg(e.target.value)}
#                       placeholder={getMessagePlaceholder(newTeam)}
#                       rows={5}
#                       className="w-full px-3 py-2.5 rounded-lg text-sm outline-none resize-none"
#                       style={{
#                         background:
#                           "color-mix(in srgb, var(--primary) 6%, transparent)",
#                         border: "1px solid var(--sidebar-border)",
#                         color: "var(--text-main)",
#                       }}
#                     />
#                   </div>

#                   <button
#                     onClick={() => {
#                       void (async () => {
#                         await createTicket();
#                       })();
#                     }}
#                     disabled={
#                       !newMsg.trim() ||
#                       !newTeam ||
#                       creating ||
#                       teamsLoading ||
#                       !newSubject.trim() ||
#                       !newSubject
#                     }
#                     className="w-full flex items-center justify-center gap-2 py-3 rounded-lg text-sm font-bold transition-all disabled:opacity-50"
#                     style={{ background: "var(--primary)", color: "white" }}
#                   >
#                     {creating ? (
#                       <Loader2 size={15} className="animate-spin" />
#                     ) : (
#                       <Send size={15} />
#                     )}
#                     {creating ? "Raising ticket…" : "Submit Ticket"}
#                   </button>
#                 </div>
#               )}

#               {/* ── CHAT VIEW ─────────────────────────────────────────────── */}
#               {view === "chat" && activeTicket && (
#                 <>
#                   <div
#                     className="px-4 py-2 shrink-0 flex items-center gap-2"
#                     style={{
#                       borderBottom: "1px solid var(--sidebar-border)",
#                       background:
#                         "color-mix(in srgb, var(--primary) 4%, transparent)",
#                     }}
#                   >
#                     <Ticket
#                       size={11}
#                       style={{ color: "var(--sidebar-muted)" }}
#                     />
#                     <span
#                       className="text-[10px] font-mono"
#                       style={{ color: "var(--sidebar-muted)" }}
#                     >
#                       {activeTicket.ticket_id} · {activeTicket.assigned_team}{" "}
#                       team
#                     </span>
#                   </div>

#                   <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
#                     {/* Original message */}
#                     <MessageBubble
#                       isAdmin={false}
#                       message={activeTicket.message}
#                       time={activeTicket.created_at}
#                       label="You"
#                       pending={false}
#                       sent={true}
#                     />

#                     {activeTicket.replies?.map((r) =>
#                       r.reply_type === "forwarded" ? (
#                         <ForwardedNote key={r.id} reply={r} />
#                       ) : (
#                         <MessageBubble
#                           key={r.id}
#                           isAdmin={r.is_admin === 1}
#                           message={r.message}
#                           time={r.created_at}
#                           label={r.is_admin === 1 ? "Support" : "You"}
#                           pending={r.pending === true}
#                           sent={!r.pending && r.is_admin === 0}
#                         />
#                       ),
#                     )}

#                     {/* Closed ticket banner */}
#                     {activeTicket.status === "closed" && (
#                       <div className="flex flex-col items-center gap-3 py-4">
#                         <div
#                           className="flex items-center justify-center w-12 h-12 rounded-full"
#                           style={{
#                             background: "rgba(34,197,94,0.12)",
#                             border: "1px solid rgba(34,197,94,0.25)",
#                           }}
#                         >
#                           <CheckCircle2
#                             size={22}
#                             style={{ color: "#22c55e" }}
#                           />
#                         </div>
#                         <div className="text-center">
#                           <p
#                             className="text-xs font-bold mb-1"
#                             style={{ color: "#22c55e" }}
#                           >
#                             Ticket Resolved
#                           </p>
#                           <p
#                             className="text-[10px] leading-relaxed"
#                             style={{ color: "var(--sidebar-muted)" }}
#                           >
#                             This ticket has been closed by our support team.
#                             <br />
#                             We hope your issue was fully resolved!
#                           </p>
#                         </div>
#                       </div>
#                     )}

#                     <div ref={bottomRef} />
#                   </div>

#                   {/* Reply input — hidden when closed */}
#                   {activeTicket.status !== "closed" && (
#                     <div
#                       className="shrink-0 px-3 py-3"
#                       style={{ borderTop: "1px solid var(--sidebar-border)" }}
#                     >
#                       <div
#                         className="flex items-end gap-2 rounded-xl px-3 py-2"
#                         style={{
#                           background:
#                             "color-mix(in srgb, var(--primary) 6%, transparent)",
#                           border: "1px solid var(--sidebar-border)",
#                         }}
#                       >
#                         <textarea
#                           ref={inputRef}
#                           rows={1}
#                           value={msg}
#                           onChange={(e) => setMsg(e.target.value)}
#                           onKeyDown={(e) => {
#                             if (e.key === "Enter" && !e.shiftKey) {
#                               e.preventDefault();
#                               void (async () => {
#                                 await sendReply();
#                               })();
#                             }
#                           }}
#                           placeholder="Type a message…"
#                           className="flex-1 resize-none text-sm bg-transparent outline-none"
#                           style={{ color: "var(--text-main)", maxHeight: 80 }}
#                         />
#                         <button
#                           onClick={() => {
#                             void (async () => {
#                               await sendReply();
#                             })();
#                           }}
#                           disabled={!msg.trim() || sending}
#                           className="p-2 rounded-lg transition-all disabled:opacity-40 shrink-0"
#                           style={{
#                             background: "var(--primary)",
#                             color: "white",
#                           }}
#                         >
#                           {sending ? (
#                             <Loader2 size={14} className="animate-spin" />
#                           ) : (
#                             <Send size={14} />
#                           )}
#                         </button>
#                       </div>
#                       <p
#                         className="text-[9px] mt-1 text-center"
#                         style={{ color: "var(--sidebar-muted)" }}
#                       >
#                         Enter to send · Shift+Enter for newline
#                       </p>
#                     </div>
#                   )}

#                   {/* Locked footer when closed */}
#                   {activeTicket.status === "closed" && (
#                     <div
#                       className="shrink-0 flex items-center justify-center gap-1.5 py-2.5"
#                       style={{ borderTop: "1px solid var(--sidebar-border)" }}
#                     >
#                       <Lock
#                         size={10}
#                         style={{ color: "var(--sidebar-muted)" }}
#                       />
#                       <span
#                         className="text-[10px]"
#                         style={{ color: "var(--sidebar-muted)" }}
#                       >
#                         Replies are locked for closed tickets
#                       </span>
#                     </div>
#                   )}
#                 </>
#               )}
#             </div>
#           </motion.div>
#         )}
#       </AnimatePresence>

#       <SidebarTrigger
#         open={open}
#         setOpen={handleToggleOpen}
#         hasUnread={hasUnread}
#       />
#     </>
#   );
# }

# // ─── Sidebar trigger ──────────────────────────────────────────────────────────
# export function SidebarTrigger({ open, setOpen, hasUnread }) {
#   return (
#     <button
#       onClick={() => setOpen((p) => !p)}
#       className="relative w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-semibold transition-all group"
#       style={{
#         background: open
#           ? "color-mix(in srgb, var(--primary) 15%, transparent)"
#           : "color-mix(in srgb, var(--primary) 7%, transparent)",
#         border: open
#           ? "1px solid color-mix(in srgb, var(--primary) 35%, transparent)"
#           : "1px dashed color-mix(in srgb, var(--primary) 30%, transparent)",
#         color: "var(--text-main)",
#       }}
#     >
#       {hasUnread && (
#         <span className="absolute -top-1 -right-1 flex h-3 w-3">
#           <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
#           <span className="relative inline-flex rounded-full h-3 w-3 bg-red-500" />
#         </span>
#       )}
#       <HeadphonesIcon
#         size={16}
#         style={{ color: open ? "var(--primary)" : "var(--sidebar-main)" }}
#         className="group-hover:scale-110 transition-transform"
#       />
#       <span className="flex-1 text-left tracking-tight">Support</span>
#       {hasUnread && (
#         <span className="text-[9px] font-black px-1.5 py-0.5 rounded-full bg-red-500 text-white">
#           NEW
#         </span>
#       )}
#     </button>
#   );
# }

# // ─── Sub-components ───────────────────────────────────────────────────────────
# // sent    = confirmed by server (only shown on user's own messages)
# function MessageBubble({
#   isAdmin,
#   message,
#   time,
#   label,
#   pending = false,
#   sent = false,
# }) {
#   return (
#     <div
#       className={`flex flex-col gap-1 ${isAdmin ? "items-start" : "items-end"}`}
#     >
#       <span
#         className="text-[9px] font-bold uppercase tracking-widest px-1"
#         style={{ color: "var(--sidebar-muted)" }}
#       >
#         {label}
#       </span>
#       <div
#         className="max-w-[82%] px-3 py-2 rounded-2xl text-sm leading-relaxed"
#         style={
#           isAdmin
#             ? {
#                 background:
#                   "color-mix(in srgb, var(--primary) 10%, transparent)",
#                 border:
#                   "1px solid color-mix(in srgb, var(--primary) 20%, transparent)",
#                 color: "var(--text-main)",
#                 borderTopLeftRadius: 4,
#               }
#             : {
#                 background: pending
#                   ? "color-mix(in srgb, var(--primary) 60%, transparent)"
#                   : "var(--primary)",
#                 color: "white",
#                 borderTopRightRadius: 4,
#                 opacity: pending ? 0.75 : 1,
#               }
#         }
#       >
#         {message}
#       </div>

#       {/* Timestamp + status row */}
#       <div className="flex items-center gap-1 px-1">
#         <span className="text-[9px]" style={{ color: "var(--sidebar-muted)" }}>
#           {fmt(time)}
#         </span>

#         {/* Pending: clock spinner */}
#         {!isAdmin && pending && (
#           <Clock
#             size={9}
#             style={{ color: "var(--sidebar-muted)" }}
#             className="opacity-60"
#           />
#         )}

#         {/* Sent: green double-check */}
#         {!isAdmin && !pending && sent && (
#           <span
#             className="flex items-center gap-0.5 text-[9px] font-semibold"
#             style={{ color: "#22c55e" }}
#           >
#             <Check size={9} strokeWidth={3} />
#             <Check size={9} strokeWidth={3} style={{ marginLeft: -4 }} />
#             Sent
#           </span>
#         )}
#       </div>
#     </div>
#   );
# }

# function ForwardedNote({ reply }) {
#   return (
#     <div className="flex justify-center">
#       <span
#         className="text-[9px] px-3 py-1 rounded-full font-semibold"
#         style={{
#           background: "color-mix(in srgb, #f59e0b 12%, transparent)",
#           color: "#f59e0b",
#           border: "1px solid color-mix(in srgb, #f59e0b 25%, transparent)",
#         }}
#       >
#         {reply.message}
#       </span>
#     </div>
#   );
# }
