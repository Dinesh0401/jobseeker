// ============================================================
// Job Hunter v1 — Telegram Webhook Edge Function
// Runtime: Deno (Supabase Edge Functions)
// Spec Reference: Technical_Specification.md §6
//
// This function acts SOLELY as a queue mutator.
// It does NOT execute SMTP operations or call external APIs.
//
// SECURITY:
//   1. X-Telegram-Bot-Api-Secret-Token header verification
//   2. Chat ID whitelist
//   3. Idempotent status check (.eq status QUEUED)
// ============================================================

import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from "https://esm.sh/@supabase/supabase-js@2"

const supabase = createClient(
  Deno.env.get('SUPABASE_URL') ?? '',
  Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
)

const TELEGRAM_BOT_TOKEN = Deno.env.get('TELEGRAM_BOT_TOKEN') ?? ''
const MY_TELEGRAM_CHAT_ID = Deno.env.get('MY_TELEGRAM_CHAT_ID') ?? ''
const WEBHOOK_SECRET = Deno.env.get('TELEGRAM_WEBHOOK_SECRET') ?? ''

serve(async (req) => {
  try {
    // ── Security Layer 1: Verify Telegram secret token ──
    // This header is set when you register the webhook with
    // ?secret_token=YOUR_SECRET. Telegram includes it on every call.
    if (WEBHOOK_SECRET) {
      const headerSecret = req.headers.get('x-telegram-bot-api-secret-token')
      if (headerSecret !== WEBHOOK_SECRET) {
        console.warn('Invalid webhook secret token')
        return new Response("Forbidden", { status: 403 })
      }
    }

    const payload = await req.json()

    // Handle /start command
    if (payload.message?.text === '/start') {
      const chatId = payload.message.chat.id
      if (chatId.toString() === MY_TELEGRAM_CHAT_ID) {
        await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chat_id: chatId,
            text: "🤖 *Job Hunter v1* is active.\n\nI'll send matched jobs for your review.",
            parse_mode: "Markdown"
          })
        })
      }
      return new Response("OK")
    }

    // Only process callback queries (button presses)
    if (!payload.callback_query) return new Response("OK")

    const chatId = payload.callback_query.message.chat.id
    const messageId = payload.callback_query.message.message_id
    const callbackQueryId = payload.callback_query.id
    const actionData = payload.callback_query.data

    // ── Security Layer 2: Chat ID whitelist ──
    if (chatId.toString() !== MY_TELEGRAM_CHAT_ID) {
      console.warn(`Unauthorized callback from chat_id: ${chatId}`)
      await answerCallback(callbackQueryId, "⛔ Unauthorized")
      return new Response("Forbidden", { status: 403 })
    }

    // ── Parse callback data: "approve:<uuid>" or "skip:<uuid>" ──
    const colonIdx = actionData.indexOf(':')
    if (colonIdx === -1) {
      await answerCallback(callbackQueryId, "❌ Invalid format")
      return new Response("OK")
    }
    const action = actionData.substring(0, colonIdx)
    const queueId = actionData.substring(colonIdx + 1)

    if (action === "approve") {
      // Idempotent: only mutate if currently QUEUED
      const { data, error } = await supabase
        .from('action_queue')
        .update({ status: 'APPROVED_FOR_DISPATCH', approved_at: new Date().toISOString() })
        .eq('id', queueId)
        .eq('status', 'QUEUED')
        .select()

      if (error) {
        console.error('Approve error:', error)
        await answerCallback(callbackQueryId, "❌ Database error")
        return new Response("OK")
      }

      if (!data || data.length === 0) {
        // Already processed — idempotent response
        await answerCallback(callbackQueryId, "⚠️ Already processed")
      } else {
        // Also transition job state via the PG function
        const { error: rpcError } = await supabase.rpc('transition_job_state', {
          p_job_id: data[0].job_id,
          p_new_state: 'APPROVED'
        })
        if (rpcError) {
          console.error('Job state transition failed:', rpcError)
          // Rollback queue
          await supabase.from('action_queue')
            .update({ status: 'QUEUED', approved_at: null })
            .eq('id', queueId)
          await answerCallback(callbackQueryId, "❌ State transition failed")
          return new Response("OK")
        }

        await answerCallback(callbackQueryId, "✅ Approved!")
        await editMessage(chatId, messageId,
          payload.callback_query.message.text + "\n\n✅ **APPROVED FOR DISPATCH**"
        )
      }

    } else if (action === "skip") {
      // Mark queue item done, transition job to REJECTED
      const { data } = await supabase
        .from('action_queue')
        .update({ status: 'DONE' })
        .eq('id', queueId)
        .eq('status', 'QUEUED')
        .select()

      if (data && data.length > 0) {
        await supabase.rpc('transition_job_state', {
          p_job_id: data[0].job_id,
          p_new_state: 'REJECTED'
        })
      }

      await answerCallback(callbackQueryId, "❌ Skipped")
      await editMessage(chatId, messageId,
        payload.callback_query.message.text + "\n\n❌ **SKIPPED**"
      )
    }

    return new Response("OK")
  } catch (err) {
    console.error("Webhook error:", err)
    // Always 200 to Telegram to prevent infinite retries
    return new Response("OK", { status: 200 })
  }
})

// ── Helpers ──

async function answerCallback(callbackQueryId: string, text: string) {
  await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/answerCallbackQuery`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ callback_query_id: callbackQueryId, text })
  })
}

async function editMessage(chatId: number, messageId: number, text: string) {
  await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/editMessageText`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      message_id: messageId,
      text,
      parse_mode: "Markdown"
    })
  })
}
